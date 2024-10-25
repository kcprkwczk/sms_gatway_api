import sys
import gammu
import logging

# Configure logging
logging.basicConfig(filename='incoming_call.log', level=logging.DEBUG)

def load_user_data(filename='credentials.txt'):
    users = {}
    with open(filename) as credentials:
        for line in credentials:
            username, password = line.partition(":")[::2]
            users[username.strip()] = password.strip()
    return users

def load_missed_calls(filename='missed_calls.txt'):
    calls = []
    with open(filename) as missed_calls:
        for line in missed_calls:
            calls.append(line.strip())
    return calls

def save_missed_calls(calls, filename='missed_calls.txt'):
    with open(filename, 'w') as missed_calls:
        for call in calls:
            missed_calls.write(call + '\n')

def init_state_machine(pin, filename='gammu.config'):
    sm = gammu.StateMachine()
    sm.ReadConfig(Filename=filename)
    sm.Init()

    if sm.GetSecurityStatus() == 'PIN':
        if pin is None or pin == '':
            print("PIN is required.")
            sys.exit(1)
        else:
            sm.EnterSecurityCode('PIN', pin)
    return sm

def retrieveAllSms(machine):
    status = machine.GetSMSStatus()
    allMultiPartSmsCount = status['SIMUsed'] + status['PhoneUsed'] + status['TemplatesUsed']

    allMultiPartSms = []
    start = True

    while len(allMultiPartSms) < allMultiPartSmsCount:
        if start:
            currentMultiPartSms = machine.GetNextSMS(Start=True, Folder=0)
            start = False
        else:
            currentMultiPartSms = machine.GetNextSMS(Location=currentMultiPartSms[0]['Location'], Folder=0)
        allMultiPartSms.append(currentMultiPartSms)

    allSms = gammu.LinkSMS(allMultiPartSms)

    results = []
    for sms in allSms:
        smsPart = sms[0]

        result = {
            "Date": str(smsPart['DateTime']),
            "Number": smsPart['Number'],
            "State": smsPart['State'],
            "Locations": [smsPart['Location'] for smsPart in sms],
        }

        decodedSms = gammu.DecodeSMS(sms)
        if decodedSms is None:
            result["Text"] = smsPart['Text']
        else:
            text = ""
            for entry in decodedSms['Entries']:
                if entry['Buffer'] is not None:
                    text += entry['Buffer']

            result["Text"] = text

        results.append(result)

    return results

def deleteSms(machine, sms):
    list(map(lambda location: machine.DeleteSMS(Folder=0, Location=location), sms["Locations"]))

def encodeSms(smsinfo):
    return gammu.EncodeSMS(smsinfo)

def incoming_call_callback(state_machine, event_type, event_data):
    logging.debug("Callback function called")
    logging.debug(f"Event type: {event_type}, Event data: {event_data}")
    if event_type == 'IncomingCall':
        call_info = f"Incoming call from: {event_data['Number']}, Date/Time: {event_data['DateTime']}\n"
        with open('missed_calls.txt', 'a') as file:
            file.write(call_info)
        logging.debug(f"Call info written to file: {call_info}")
