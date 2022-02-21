import json
import time
import asyncio
import logging
import traceback
import aiohttp
import aiofiles
import paho.mqtt.client as mqtt

import configparser
config = configparser.ConfigParser()
config.read('config.ini')

try:
    from heran_customize import timer
except ModuleNotFoundError:
    import sys

    sys.path.append('../mqtt/python3/lib')
    from heran_customize import timer

AUTRON_URL = config['TWM']['AUTRON_URL']
HEADER = {'Authorization': config['TWM']['Authorization']}

HERAN_URL =  config['Heran']['HERAN_URL']
VAL = {'pass':  config['Heran']['pass']}

# LOG_PATH = ''
LOG_PATH = config['other']['LOG_PATH']

# ID be directed to fan mac
mac_dict = dict()
# mac be directed to ID
id_dict = dict()
fan_status = dict()
amiba_payloads = dict()
all_mac = set()
all_user = set()
LOG_NL = '\n\t'
TIMEOUT = aiohttp.ClientTimeout(total=3)
WEIGHTING = .1

OFFLINE_INDEX = 6


# def original_pow_switch(argument):
#     switcher = {0: "關",
#                 1: "開"}
#     return switcher[argument]
#
#
# def original_wind_mode(argument):
#     switcher = {0: "一般風",
#                 1: "自然風",
#                 2: "睡眠風"}
#     return switcher[argument]
#
#
# def original_turn_direction(argument):
#     switcher = {0: "關",
#                 1: "開", }
#     return switcher[argument]


def autron_payload(mac, user):
    mode1 = fan_status[mac]['mode1']
    if fan_status[mac]['eco']:
        mode1 = '4'
    return {
        "agentUid": f"{user}",
        "devices": {
            f"BY2N00-[{mac}]": {
                "states": {
                    "FAN": {
                        "on": fan_status[mac]['on'],
                        "currentModeSettings": {
                            "mode1": mode1,
                            "mode2": fan_status[mac]['speed_mode2'],
                            "mode3": fan_status[mac]['light_mode3']
                        },
                        "currentToggleSettings": {
                            "toggle1": fan_status[mac]['sway_toggle1']
                        },
                        'temperatureAmbientCelsius':fan_status[mac]['temperatureAmbientCelsius']
                    }
                },
                "online": fan_status[mac]['online']
            }
        }
    }


def pow_switch(argument):
    switcher = {0: False,
                1: True}
    return switcher[argument]


def wind_mode(argument):
    switcher = {0: '2',
                1: '3',
                2: '1'}
    return switcher[argument]


def turn_direction(argument):
    switcher = {0: False,
                1: True, }
    return switcher[argument]


def light_mode(argument):
    light = {
        0: '1',
        1: '2',
        2: '3'
    }
    return light[argument]


# def speed_parsing(argument):
#     if argument < 9:
#         return '1'
#     elif argument < 17:
#         return '2'
#     else:
#         return '3'
def speed_parsing(argument):
    if argument == 0:
        argument = 1
    return str(argument)


def parsing(byt, payload, carry=16):
    pl = payload[byt * 2: byt * 2 + 2]
    return int(pl, carry) ^ int("FF", carry)


def mark_dirty(mac):
    fan_status[mac]['dirty'] = True


def reset_dirty(mac):
    fan_status[mac]['dirty'] = False
    logging.debug(f"reset_dirty:{mac}\n\tfan_status[{mac}]: {fan_status[mac]}")


def change_switch_status(mac, status_index):
    logging.debug(f'{mac}: change_switch_status to {pow_switch(status_index)}')
    fan_status[mac]['on'] = pow_switch(status_index)
    mark_dirty(mac)


def change_mode_status(mac, status_index):
    logging.debug(f'{mac}: change_mode_status to {wind_mode(status_index)}')
    fan_status[mac]['mode1'] = wind_mode(status_index)
    mark_dirty(mac)


def change_speed_status(mac, status_index):
    logging.debug(f'{mac}: change_speed_status to {speed_parsing(status_index)}')
    fan_status[mac]['speed_mode2'] = speed_parsing(status_index)
    mark_dirty(mac)


def change_sway_status(mac, status_index):
    logging.debug(f'{mac}: change_sway_status to {turn_direction(status_index)}')
    fan_status[mac]['sway_toggle1'] = turn_direction(status_index)
    mark_dirty(mac)


def change_online_status(mac, status_index: bool):
    logging.debug(f'{mac}: change_online_status to {status_index}')
    fan_status[mac]['online'] = status_index
    mark_dirty(mac)


def change_light_status(mac, status_index):
    logging.debug(f'{mac}: change_light_status to {status_index}')
    fan_status[mac]['light_mode3'] = light_mode(status_index)
    mark_dirty(mac)


def change_eco_status(mac, status_index):
    logging.debug(f'{mac}: change_eco_status to {status_index}')
    fan_status[mac]['eco'] = status_index
    mark_dirty(mac)

def change_temperatureAmbientCelsius_status(mac, status_index):
    logging.debug(f'{mac}: change_temperatureAmbientCelsius_status to {status_index}')
    fan_status[mac]['temperatureAmbientCelsius'] = status_index
    mark_dirty(mac)

# 刪除已完成的amiba_payloads
def remove_amiba_payloads(mac):
    logging.debug(f'{mac} -> del amiba_payloads[{mac}][0] : {amiba_payloads[mac][0]}')
    del amiba_payloads[mac][0]
    size = len(amiba_payloads[mac])
    logging.debug(f'len(amiba_payloads[{mac}]): {size}')
    if size > 1:
        logging.debug(f'amiba_payloads[{mac}]:\n\t {LOG_NL.join([str(d) for d in amiba_payloads[mac]])}')
        amiba_payloads[mac] = [amiba_payloads[mac][-1]]
        logging.debug(f'amiba_payloads[{mac}]: {amiba_payloads[mac]}')


# initialization account/mac data
@timer
async def get_fan_mac():
    dev = 'fan'
    async with aiohttp.ClientSession() as session:
        async with session.post(HERAN_URL, data=VAL) as her_resp:
            if her_resp.status == 200:
                id_mac_dict = json.loads(str(await her_resp.read())[2:-1])
                # id_mac_dict = {'luck4268@gmail.com': {'fan': ['a00abf1ddb37']}}
                with open(f'{LOG_PATH}heran_post.txt', 'a', encoding='utf-8') as f:
                    f.write(f'{time.strftime("%Y-%m-%d %X")}\nid_mac: {id_mac_dict}\n\n')
                # id_mac_dict = {'eric.hsieh@wifigarden.com': {'fan': ['a00abf395aab']},
                #                'luck4268@gmail.com': {'fan': ['a00abf1ddb37']},
                #                'berlin.lu@wifigarden.com': {'fan': ['a00abf394a65']},
                #                'ray.lin@wifigarden.com': {'fan': ['a00abf395aab', 'a00abf394a65']},
                #                'jessica.liu@wifigarden.com': {'fan': ['a00abf395aab']},
                #                'wing.lee@wifigarden.com': {'fan': ['a00abf394a65']},
                #                'chongjyu98@gmail.com': {'fan': ['a00abf1ddb37']}}
                # id_mac_dict = {'luck4268@gmail.com': {'fan': ['a00abf1ddb37']},
                #                'chongjyu98@gmail.com': {'fan': ['a00abf1ddb37']}}
                logging.info(f'her status: {her_resp.status}\n\tid_mac_dict: {id_mac_dict}')
                for user, device in id_mac_dict.items():
                    if id_mac_dict[user].get(dev):
                        for mac in id_mac_dict[user][dev]:
                            if mac not in mac_dict:
                                mac_dict[mac] = [user]
                            else:
                                mac_dict[mac].append(user)
                        id_dict[user] = id_mac_dict[user][dev]
                        all_user.add(user)
            else:
                raise AssertionError(f"Status: {her_resp.status}\nCan't get fan mac")

    for mac, v in mac_dict.items():
        all_mac.add(mac)
    logging.debug(f'id_dict: {id_dict}\n\tmac_dict: {mac_dict}\n\tall_mac: {all_mac}\n\tall_user: {all_user}')


# initialization autron server
async def init_autron_status(session, mac):
    init_index = True
    while init_index:
        # logging.debug(f'fan_status.get({mac}): {fan_status.get(mac)}')
        # if fan_status.get(mac):
        logging.debug(f"fan_status[{mac}]['autron_init']: {fan_status[mac]['autron_init']}")
        if not fan_status[mac]['autron_init']:
            u = None
            try:
                for user in mac_dict[mac]:
                    u = user
                    async with session.post(AUTRON_URL, data=json.dumps(autron_payload(mac, user))) as resp:
                        if resp.status == 200:
                            logging.debug(f'{user}, autron_init: {resp.status}')
                            # async with aiofiles.open(f'send/{u}.txt', 'a', encoding='utf-8') as f:
                            #     await f.write(f'{u} -> 200(init)\nsend -> {autron_payload(mac, user)}\n'
                            #                   f'{time.strftime("%Y-%m-%d %X")}\n\n')
                        else:
                            r = await resp.text()
                            logging.info(f'{user}, autron_init: {resp.status}')
                            with open(f'{LOG_PATH}Log/{mac}.txt', 'a', encoding='utf-8') as f:
                                f.write(f'status: {resp.status} -> {r}user: {user}, mac: {mac}\n'
                                        f'init_autron_status -> {time.strftime("%Y-%m-%d %X")}\n\n')
                            raise AssertionError(f"Status: {resp.status}\nuser: {user}, mac: {mac}\nresp: {r}"
                                                 f"Check account status -> {user}")
                fan_status[mac]['autron_init'] = True
                init_index = False
                logging.info(f'{mac} initialization completion.')
            except asyncio.TimeoutError:
                logging.info(f'{u}: TimeoutError\n\tmac: {mac}, init_autron_status')
                async with aiofiles.open(f'{LOG_PATH}timeout/{mac}.txt', 'a', encoding='utf-8') as f:
                    await f.write(f'user: {u}, mac: {mac} Timeout\n'
                                  f'init_autron_status, {time.strftime("%Y-%m-%d %X")}\n\n')
        await asyncio.sleep(1)
        # else:
        #     await asyncio.sleep(1)


def status_index_update(status_index, mac, user):
    if status_index == 'status':
        logging.debug(f'amiba_payloads[{mac}]: {amiba_payloads[mac]}')
        if amiba_payloads[mac]:  # if is none, device is offline,schedule is None
            amiba_payloads[mac][0]['schedule'][user] = True
            logging.debug(f'amiba_payloads[mac][0]: {amiba_payloads[mac][0]}')
    elif status_index == 'online':
        # make sure online status
        if not amiba_payloads[mac]:
            fan_status[mac]['alive_index']['live_schedule'][user] = True
        logging.debug(f'fan_status[mac]: {fan_status[mac]}')


@timer
async def update_autron_status(session, mac, user, status_index: str):
    try:
        logging.info(f"user: {user}\n\tsend({status_index}) -> {autron_payload(mac, user)}")
        async with session.post(AUTRON_URL, data=json.dumps(autron_payload(mac, user))) as resp:
            if resp.status == 200:
                logging.info(f'{user}, change_fan_status: {mac}, {resp.status}')
                # async with aiofiles.open(f'send/{user}.txt', 'a', encoding='utf-8') as f:
                #     await f.write(f'{user} -> 200({status_index})\nsend -> {autron_payload(mac, user)}\n'
                #                   f'{time.strftime("%Y-%m-%d %X")}\n\n')
            else:
                r = await resp.text()
                with open(f'{LOG_PATH}Log/{mac}.txt', 'a', encoding='utf-8') as f:
                    f.write(f'status: {resp.status} -> {r}user: {user}, mac: {mac}\n'
                            f'{time.strftime("%Y-%m-%d %X")}\n\n')
                logging.info(f'status_code: {resp.status} -> {r}')
                raise AssertionError(f"Status: {resp.status}\nuser: {user}, mac: {mac}\nresp: {r}"
                                     f"Check account status -> {user}")
            status_index_update(status_index, mac, user)
    except asyncio.TimeoutError:
        # status_index_update(status_index, mac, user)
        logging.info(f'{user}: TimeoutError\n\tmac: {mac}')
        async with aiofiles.open(f'{LOG_PATH}timeout/{mac}.txt', 'a', encoding='utf-8') as f:
            await f.write(f'user: {user}, mac: {mac} Timeout\n{time.strftime("%Y-%m-%d %X")}\n\n')


def check_fan_status(mac, payload):
    # code_list = [parsing(bt, payload) for bt in range(int((len(payload) - 22) / 2))]
    # print(f'switch_status: {pow_switch(code_list[3])}, speed: {code_list[4]}, '
    #       f'mode: {wind_mode(code_list[5])}, sway: {turn_direction(code_list[6])}')

    # code_list = [parsing(bt, payload) for bt in range(3, 7)]

    # new
    code_list = [parsing(bt, payload) for bt in range(3, 10)]
    try:
        logging.debug(f"{mac} now status: {fan_status[mac]}\n\tswitch_status: {pow_switch(code_list[0])},"
                      f" original_speed: {code_list[1]}, mode: {wind_mode(code_list[2])}, "
                      f"sway: {turn_direction(code_list[3])}")
        if pow_switch(code_list[0]) != fan_status[mac]['on']:
            change_switch_status(mac, code_list[0])
        if speed_parsing(code_list[1]) != fan_status[mac]['speed_mode2']:
            change_speed_status(mac, code_list[1])
        if wind_mode(code_list[2]) != fan_status[mac]['mode1']:
            change_mode_status(mac, code_list[2])
        if turn_direction(code_list[3]) != fan_status[mac]['sway_toggle1']:
            change_sway_status(mac, code_list[3])
        if light_mode(code_list[4]) != fan_status[mac]['light_mode3']:
            change_light_status(mac, code_list[4])
        if code_list[6] != fan_status[mac]['eco']:
            change_eco_status(mac, code_list[6])
        if code_list[5] != fan_status[mac]['temperatureAmbientCelsius']:
            change_temperatureAmbientCelsius_status(mac, code_list[5])
      
    except KeyError as err:
        logging.info(f'what is this?  {payload}')
        print(err)
        # with open(f'what_is_this {mac}.txt', 'a', encoding='utf-8') as f:  #可抓有問題的環控碼
        #     f.write(f'{payload}\nKeyError: {err}, {time.strftime("%Y-%m-%d %X")}\n\n')

    if fan_status[mac]['online'] is False:
        change_online_status(mac, True)
        # reset live_schedule
        # for user, v in fan_status[mac]['alive_index']['live_schedule'].items():
        #     fan_status[mac]['alive_index']['live_schedule'][user] = False

    logging.debug(f"status: {fan_status[mac]}")


# update_server
# just dirty
# change live_schedule
async def check_dirty_status(session, user):
    while True:
        for mac in id_dict[user]:
            # logging.debug(f'{user}: check_dirty_status Start\n\tfan_status.get({mac}): {fan_status.get(mac)}')
            # logging.info(f'{user}: check_dirty_status Start\n\tfan_status.get({mac}): {fan_status.get(mac)}')
            # if fan_status.get(mac):
            logging.debug(f"fan_status[{mac}]['dirty']: {fan_status[mac]['dirty']}")
            if fan_status[mac]['dirty']:
                live_time = time.time() - fan_status[mac]['alive_index']['time']
                logging.debug(f'live_time: {live_time}')
                if live_time > OFFLINE_INDEX:
                    logging.debug(f'amiba_payloads[{mac}]: {amiba_payloads[mac]}')
                    # make sure status
                    if not amiba_payloads[mac]:
                        logging.debug(f"fan_status[{mac}]['alive_index']['live_schedule'][{user}]: "
                                      f"{fan_status[mac]['alive_index']['live_schedule'][user]}")
                        if fan_status[mac]['alive_index']['live_schedule'][user] is False:
                            await update_autron_status(session, mac, user, 'online')
                elif amiba_payloads[mac]:
                    logging.debug(f"amiba_payloads[{mac}][0]['internal_status_index']: "
                                  f"{amiba_payloads[mac][0]['internal_status_index']}")
                    # make sure status
                    if amiba_payloads[mac][0]['internal_status_index']:
                        logging.debug(f"amiba_payloads[{mac}][0]['schedule'][{user}]: "
                                      f"{amiba_payloads[mac][0]['schedule'][user]}")
                        if amiba_payloads[mac][0]['schedule'][user] is False:
                            await update_autron_status(session, mac, user, 'status')
        await asyncio.sleep(WEIGHTING)


# dirty status and internal_status_index manager
# reset_dirty
# amiba_payloads manager
# online manager
async def update_internal_status(mac):
    while True:
        # logging.debug(f"fan_status.get({mac}): {fan_status.get(mac)}")
        # if fan_status.get(mac):
        logging.debug(f"fan_status[{mac}]['autron_init']: {fan_status[mac]['autron_init']}")
        if fan_status[mac]['autron_init']:
            live_time = time.time() - fan_status[mac]['alive_index']['time']
            logging.debug(f"live_time: {live_time}\n\tamiba_payloads[{mac}]: \n\t"
                          f"{LOG_NL.join([str(d) for d in amiba_payloads[mac]])}")
            if live_time > OFFLINE_INDEX:
                logging.debug(f"amiba_payloads[{mac}]: {amiba_payloads[mac]}")
                if amiba_payloads[mac]:
                    amiba_payloads[mac].clear()
                    logging.debug(f'amiba_payloads[{mac}]: {amiba_payloads[mac]}')

                logging.debug(f"fan_status[{mac}]['online']: {fan_status[mac]['online']}")
                if fan_status[mac]['online'] is True:
                    change_online_status(mac, False)

                elif fan_status[mac]['dirty']:
                    logging.debug(f"fan_status[{mac}]['dirty']: {fan_status[mac]['dirty']}")
                    index = 0
                    all_schedule_index = len(fan_status[mac]['alive_index']['live_schedule'])
                    logging.debug(f"len(fan_status[{mac}]['alive_index']['live_schedule']: {all_schedule_index}")
                    for u, schedule in fan_status[mac]['alive_index']['live_schedule'].items():
                        if schedule:
                            index += 1
                    logging.debug(f"fan_status[{mac}]['alive_index']['live_schedule']: "
                                  f"{fan_status[mac]['alive_index']['live_schedule']}\n\tindex: {index}")
                    if index == all_schedule_index:
                        logging.debug(f'index == all_schedule_index: {index == all_schedule_index}')
                        reset_dirty(mac)

            elif amiba_payloads[mac]:
                # logging.debug(f"fan_status[{mac}]['online']: {fan_status[mac]['online']}")
                # if fan_status[mac]['online'] is False:  # 修正辨識到裝置離線後,在未更新澳創狀態太前,又在次辨識到連線(直接忽視掉此次離線)
                #     change_online_status(mac, True)
                #     reset_dirty(mac)
                logging.debug(f"amiba_payloads[{mac}][0]['internal_status_index']: "
                              f"{amiba_payloads[mac][0]['internal_status_index']}")
                if amiba_payloads[mac][0]['internal_status_index'] is False:
                    # mark dirty
                    check_fan_status(mac, amiba_payloads[mac][0]['payload'])
                    amiba_payloads[mac][0]['internal_status_index'] = True
                    logging.debug(f"amiba_payloads[{mac}]: {amiba_payloads[mac]}")
                else:
                    logging.debug(f"fan_status[{mac}]['dirty']: {fan_status[mac]['dirty']}")
                    if fan_status[mac]['dirty']:
                        schedule_dict = amiba_payloads[mac][0]['schedule']
                        all_schedule_index = len(schedule_dict)
                        logging.debug(f"all_schedule_index: {all_schedule_index}")
                        index = 0
                        for u, schedule in schedule_dict.items():
                            if schedule:
                                index += 1
                        logging.debug(f"index: {index}")
                        if all_schedule_index == index:
                            logging.debug(f"index == all_schedule_index: {index == all_schedule_index}")
                            reset_dirty(mac)
                            remove_amiba_payloads(mac)
                    else:
                        logging.debug(f"fan_status[mac]['dirty']: {fan_status[mac]['dirty']}")
                        remove_amiba_payloads(mac)
        await asyncio.sleep(WEIGHTING)


def initialization_status():
    for fan_mac, users in mac_dict.items():
        logging.debug(f'subscribe: {fan_mac}')
        # client.subscribe(fan_mac)
        fan_status[fan_mac] = {'on': False, 'mode1': '1', 'speed_mode2': '1', 'sway_toggle1': False, 'online': False,
                               'dirty': None, 'alive_index': {'time': time.time(), 'live_schedule': {}},
                               'autron_init': False, 'light_mode3': '1', 'eco': 0,'temperatureAmbientCelsius':20}
        for user in users:
            fan_status[fan_mac]['alive_index']['live_schedule'].update({user: False})
        logging.debug(f'fan_status[{fan_mac}]: {fan_status[fan_mac]}')
        amiba_payloads[fan_mac] = list()


def on_connect(client, userdata, flags, rc):
    for fan_mac in all_mac:
        client.subscribe(fan_mac)


def on_message(client, userdata, msg):
    payload = str(msg.payload)[2:-1]
    fan_mac = msg.topic

    if fan_mac == payload[-12:] and payload.find("Log") != 0 and payload.find("TFL") != 0:
        if parsing(2, payload) == 0x90:
            amiba_payloads[fan_mac].append({'payload': payload, 'schedule': {}, 'internal_status_index': False})
            for user in mac_dict[fan_mac]:
                amiba_payloads[fan_mac][-1]['schedule'].update({user: False})
            fan_status[fan_mac]['alive_index']['time'] = time.time()

            # online
            for user, s in fan_status[fan_mac]['alive_index']['live_schedule'].items():
                fan_status[fan_mac]['alive_index']['live_schedule'][user] = False
            logging.debug(f"fan_status[{fan_mac}][alive_index]: {fan_status[fan_mac]['alive_index']}")
            logging.debug(f'amiba_payloads[{fan_mac}]:\n\t{LOG_NL.join([str(d) for d in amiba_payloads[fan_mac]])}')


async def autron_sync():
    # initialization account/mac data
    await get_fan_mac()
    initialization_status()
    async with aiohttp.ClientSession(headers=HEADER, timeout=TIMEOUT) as session:
        init = [asyncio.create_task(init_autron_status(session, mac)) for mac in all_mac]
        internal = [asyncio.create_task(update_internal_status(mac)) for mac in all_mac]
        autron = [asyncio.create_task(check_dirty_status(session, user)) for user in all_user]
        tasks = init + internal + autron
        client = mqtt.Client()
        client.on_connect = on_connect
        client.on_message = on_message
        client.connect("59.125.190.113", 1883, 60)
        client.loop_start()
        return await asyncio.gather(*tasks)


try:
    with open(f'{LOG_PATH}start.txt', 'a', encoding='utf-8') as fil:
        fil.write(f'{time.strftime("%Y-%m-%d %X")}\n')
    asyncio.get_event_loop().run_until_complete(autron_sync())
except Exception as e:
    with open(f'{LOG_PATH}Autron_fanReportState_error.txt', 'a', encoding='utf-8') as fil:
        fil.write(f'{time.strftime("%Y-%m-%d %X")}\n{traceback.format_exc()}\n{e}\n\n')
