import os
from flask import Flask
from flask_httpauth import HTTPBasicAuth
from flask_restful import reqparse, Api, Resource, abort
import logging

from support import load_user_data, init_state_machine, retrieveAllSms, deleteSms, encodeSms, load_missed_calls, save_missed_calls, incoming_call_callback

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
        allSms = retrieveAllSms(machine)
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
        result = [machine.SendSMS(message) for message in messages]
        return {"status": 200, "message": str(result)}, 200

class Signal(Resource):
    def __init__(self, sm):
        self.machine = sm

    def get(self):
        return machine.GetSignalQuality()

class Reset(Resource):
    def __init__(self, sm):
        self.machine = sm

    def get(self):
        machine.Reset(False)
        return {"status": 200, "message": "Reset done"}, 200

class Network(Resource):
    def __init__(self, sm):
        self.machine = sm

    def get(self):
        network = machine.GetNetworkInfo()
        network["NetworkName"] = GSMNetworks.get(network["NetworkCode"], 'Unknown')
        return network

class GetSms(Resource):
    def __init__(self, sm):
        self.machine = sm

    @auth.login_required
    def get(self):
        allSms = retrieveAllSms(machine)
        sms = {"Date": "", "Number": "", "State": "", "Text": ""}
        if len(allSms) > 0:
            sms = allSms[0]
            deleteSms(machine, sms)
            sms.pop("Locations")

        return sms

class SmsById(Resource):
    def __init__(self, sm):
        self.machine = sm

    @auth.login_required
    def get(self, id):
        allSms = retrieveAllSms(machine)
        self.abort_if_id_doesnt_exist(id, allSms)
        sms = allSms[id]
        sms.pop("Locations")
        return sms

    def delete(self, id):
        allSms = retrieveAllSms(machine)
        self.abort_if_id_doesnt_exist(id, allSms)
        deleteSms(machine, allSms[id])
        return '', 204

    def abort_if_id_doesnt_exist(self, id, allSms):
        if id < 0 or id >= len(allSms):
            abort(404, message="Sms with id '{}' not found".format(id))

class MissedCalls(Resource):
    def __init__(self):
        self.call_list = load_missed_calls()

    @auth.login_required
    def get(self):
        if len(self.call_list) > 0:
            return {"missedCalls": self.call_list}
        else:
            return {"missedCalls": []}

    @auth.login_required
    def delete(self):
        if len(self.call_list) > 0:
            last_call = self.call_list.pop(0)
            save_missed_calls(self.call_list)
            return {"message": "Last missed call removed", "call": last_call}, 200
        else:
            abort(404, message="No missed calls to remove")

api.add_resource(Sms, '/sms', resource_class_args=[machine])
api.add_resource(SmsById, '/sms/<int:id>', resource_class_args=[machine])
api.add_resource(Signal, '/signal', resource_class_args=[machine])
api.add_resource(Network, '/network', resource_class_args=[machine])
api.add_resource(GetSms, '/getsms', resource_class_args=[machine])
api.add_resource(Reset, '/reset', resource_class_args=[machine])
api.add_resource(MissedCalls, '/missedCalls')

if __name__ == '__main__':
    # Register the incoming call callback
    logging.debug("Registering incoming call callback")
    machine.SetIncomingCallback(incoming_call_callback)
    # Enable listening for incoming calls
    logging.debug("Enabling incoming call listening")
    machine.SetIncomingCall(1)

    if ssl:
        app.run(port=port, host="0.0.0.0", ssl_context=('/ssl/cert.pem', '/ssl/key.pem'))
    else:
        app.run(port=port, host="0.0.0.0")
