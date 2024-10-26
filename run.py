import os
from flask import Flask
from flask_httpauth import HTTPBasicAuth
from flask_restful import reqparse, Api, Resource, abort
import logging
from datetime import datetime
from support import load_user_data, init_state_machine, retrieveAllSms, deleteSms, encodeSms

logging.basicConfig(level=logging.DEBUG)

pin = os.getenv('PIN', None)
ssl = os.getenv('SSL', False)
port = os.getenv('PORT', '5000')
user_data = load_user_data()
machine = init_state_machine(pin)
logging.debug("State machine initialized")

app = Flask(__name__)
api = Api(app)
auth = HTTPBasicAuth()


@auth.verify_password
def verify(username, password):
    if not (username and password):
        return False
    return user_data.get(username) == password


class Sms(Resource):
    def __init__(self, sm):
        self.parser = reqparse.RequestParser()
        self.parser.add_argument('text')
        self.parser.add_argument('number')
        self.parser.add_argument('smsc')
        self.parser.add_argument('unicode')
        self.machine = sm

    @auth.login_required
    def get(self):
        allSms = retrieveAllSms(self.machine)
        list(map(lambda sms: sms.pop("Locations"), allSms))
        return allSms

    @auth.login_required
    def post(self):
        args = self.parser.parse_args()
        if args['text'] is None or args['number'] is None:
            abort(404, message="Parameters 'text' and 'number' are required.")

        is_unicode = any(ord(char) > 127 for char in args['text'])

        smsinfo = {
            "Class": -1,
            "Unicode": is_unicode,
            "Entries": [
                {
                    "ID": "ConcatenatedTextLong",
                    "Buffer": args['text'],
                }
            ],
        }

        messages = []
        for number in args.get("number").split(','):
            for message in encodeSms(smsinfo):
                message["SMSC"] = {'Number': args.get("smsc")} if args.get("smsc") else {'Location': 1}
                message["Number"] = number
                messages.append(message)
        result = [self.machine.SendSMS(message) for message in messages]
        return {"status": 200, "message": str(result)}, 200


class Signal(Resource):
    def __init__(self, sm):
        self.machine = sm

    def get(self):
        return self.machine.GetSignalQuality()


class Reset(Resource):
    def __init__(self, sm):
        self.machine = sm

    def get(self):
        self.machine.Reset(False)
        return {"status": 200, "message": "Reset done"}, 200


class Network(Resource):
    def __init__(self, sm):
        self.machine = sm

    def get(self):
        network = self.machine.GetNetworkInfo()
        return network


class GetSms(Resource):
    def __init__(self, sm):
        self.machine = sm

    @auth.login_required
    def get(self):
        allSms = retrieveAllSms(self.machine)
        sms = {"Date": "", "Number": "", "State": "", "Text": ""}
        if len(allSms) > 0:
            sms = allSms[0]
            deleteSms(self.machine, sms)
            sms.pop("Locations")

        return sms


class SmsById(Resource):
    def __init__(self, sm):
        self.machine = sm

    @auth.login_required
    def get(self, id):
        allSms = retrieveAllSms(self.machine)
        self.abort_if_id_doesnt_exist(id, allSms)
        sms = allSms[id]
        sms.pop("Locations")
        return sms

    def delete(self, id):
        allSms = retrieveAllSms(self.machine)
        self.abort_if_id_doesnt_exist(id, allSms)
        deleteSms(self.machine, allSms[id])
        return '', 204

    def abort_if_id_doesnt_exist(self, id, allSms):
        if id < 0 or id >= len(allSms):
            abort(404, message="Sms with id '{}' not found".format(id))


# Callback function for incoming calls
def incoming_call_callback(machine, event_type, data):
    logging.debug(f'Event type: {event_type}, Data: {data}')  # Log event type and data
    if event_type == 'IncomingCall':
        number = data.get('Number')
        state = data.get('State')

        if state == 'Missed':
            log_missed_call(number)  # Log missed call


def log_missed_call(number):
    with open("missed_calls.log", "a") as f:
        f.write(f"Missed call from: {number} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        logging.info(f"Missed call logged: {number}")


# Setting up the incoming call notifications
machine.SetIncomingCall(True)
machine.SetIncomingCallback(incoming_call_callback)

api.add_resource(Sms, '/sms', resource_class_args=[machine])
api.add_resource(SmsById, '/sms/<int:id>', resource_class_args=[machine])
api.add_resource(Signal, '/signal', resource_class_args=[machine])
api.add_resource(Network, '/network', resource_class_args=[machine])
api.add_resource(GetSms, '/getsms', resource_class_args=[machine])
api.add_resource(Reset, '/reset', resource_class_args=[machine])

if __name__ == '__main__':
    if ssl:
        app.run(port=port, host="0.0.0.0", ssl_context=('/ssl/cert.pem', '/ssl/key.pem'))
    else:
        app.run(port=port, host="0.0.0.0")
