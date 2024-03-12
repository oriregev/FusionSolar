import logging
import random
from functools import wraps
from time import sleep
from typing import Dict

import pandas as pd
import requests


class HTTPError(Exception):
    pass


class HTTPError407(HTTPError):
    pass

class HTTPError305(HTTPError):
    pass

class HTTPError306(HTTPError):
    pass

class HTTPError307(HTTPError):
    pass

def authenticated(func):
    """
    Decorator to check if token has expired.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        self = args[0]
        if self.token_expiration_time <= pd.Timestamp.utcnow().timestamp():
            self.login()
        return func(*args, **kwargs)

    return wrapper


def throttle_retry(func):
    """
    Decorator to retry when throttleError is received.

    FusionSolar's rate limits are ridiculous:

    Login Interface: The timeout value is 30 minutes, which will be reset if any service invokes this OpenAPI in 30
    minutes. If the XSRF-TOKEN has not expired, the user does not need to log in again.

    Logout Interface: Users will be logged out upon timeout.

    Power Plant List Interface: The recommended maximum number of API calls per day is 24. This interface is used to
    obtain the list of authorized plants. If the authorized plants have not changed, there is no need to invoke this
    interface.

    Interface for Real-time Plant Data: The recommended maximum number of API calls per day is 288. The interface
    data is updated every 5 minutes.

    Interface for Hourly Plant Data: The recommended maximum number of API calls per day is 24. The interface data is
    updated every hour.

    Interface for Daily Plant Data: The recommended maximum number of API calls per day is 1. The interface data is
    updated every day.

    Interface for Yearly Plant Data: The recommended maximum number of API calls per day is 1. The interface data is
    updated every day.

    Device List Interface: This OpenAPI is mandatory if device-level data needs to be queried. The recommended maximum
    number of API calls per day is 1. When the device list has not changed, the data returned by this interface remains
    the same.

    Real-time Device Data Interface: The recommended maximum number of API calls per day is 288. The interface data is
    updated every 5 minutes.

    5-minute Device Data Interface: The recommended maximum number of API calls per day is 288. The interface data is
    updated every 5 minutes.

    Daily Device Data Interface: The recommended maximum number of API calls per day is 24. The interface data is
    updated every hour.

    Monthly Device Data Interface: The recommended maximum number of API calls per day is 1. The interface data is
    updated every day.

    Yearly Device Data Interface: The recommended maximum number of API calls per day is 1. The interface data is
    updated every day.

    Device Alarm Interface: The recommended maximum number of API calls per day is 288. The interface data is updated
    every 5 minutes.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        self = args[0]
        try:
            return func(*args, **kwargs)
        except HTTPError407 as e:
            for i in range(1, self.max_retry + 1):
                delay = i * 20 + random.randint(3, 10)
                logging.info(f'FusionSolar Client: got HTTPError407 sleeping for {delay} seconds')
                sleep(delay)
                try:
                    return func(*args, **kwargs)
                except HTTPError407:
                    pass
            else:
                raise e
        except (HTTPError305, HTTPError306, HTTPError307) as e:
            # Token as expired or we aren't logged in.. Refresh it.
            logging.debug("Got login error. Logging back in and retrying")
            self.login()
            return func(*args, **kwargs)

    return wrapper

 
class Client:
    def __init__(self, user_name: str, system_code: str, max_retry: int = 6, base_url: str = "https://eu5.fusionsolar.huawei.com/thirdData"):
        self.user_name = user_name
        self.system_code = system_code
        self.max_retry = max_retry
        self.base_url = base_url

        self.session = requests.session()
        self.session.headers.update(
            {'Connection': 'keep-alive', 'Content-Type': 'application/json'})

        self.token_expiration_time = 0

    def __enter__(self):
        self.login()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def login(self):
        url = f'{self.base_url}/login'
        body = {
            'userName': self.user_name,
            'systemCode': self.system_code
        }
        self.session.cookies.clear()
        r = self.session.post(url=url, json=body)
        self._validate_response(response=r)
        self.session.headers.update(
            {'XSRF-TOKEN': r.cookies.get(name='XSRF-TOKEN')})
        self.token_expiration_time = pd.Timestamp.utcnow().timestamp() + 1200

    @staticmethod
    def _validate_response(response: requests.Response) -> bool:
        response.raise_for_status()
        body = response.json()
        success = body.get('success', False)
        if not success:
            if body.get('failCode') == 407:
                logging.debug('Error 407')
                raise HTTPError407(body)
            elif body.get('failCode') == 305:
                logging.debug('Error 305')
                raise HTTPError306(body)
            elif body.get('failCode') == 306:
                logging.debug('Error 306')
                raise HTTPError306(body)
            elif body.get('failCode') == 307:
                logging.debug('Error 307')
                raise HTTPError306(body)
            else:
                raise HTTPError(body)
        else:
            return True

    @throttle_retry
    @authenticated
    def _request(self, function: str, data=None) -> Dict:
        if data is None:
            data = {}
        url = f'{self.base_url}/{function}'
        r = self.session.post(url=url, json=data)
        self._validate_response(r)
        return r.json()

    def get_station_list(self) -> Dict:
        return self._request("getStationList")

    def get_station_kpi_real(self, station_code: str) -> Dict:
        return self._request("getStationRealKpi",
                             {'stationCodes': station_code})

    def get_station_kpi_hour(self, station_code: str,
                             date: pd.Timestamp) -> Dict:
        time = int(date.timestamp()) * 1000
        return self._request("getKpiStationHour", {'stationCodes': station_code,
                                                   'collectTime': time})

    def get_station_kpi_day(self, station_code: str,
                            date: pd.Timestamp) -> Dict:
        time = int(date.timestamp()) * 1000
        return self._request("getKpiStationDay", {'stationCodes': station_code,
                                                  'collectTime': time})

    def get_station_kpi_month(self, station_code: str,
                              date: pd.Timestamp) -> Dict:
        time = int(date.timestamp()) * 1000
        return self._request("getKpiStationMonth",
                             {'stationCodes': station_code,
                              'collectTime': time})

    def get_station_kpi_year(self, station_code: str,
                             date: pd.Timestamp) -> Dict:
        time = int(date.timestamp()) * 1000
        return self._request("getKpiStationYear", {'stationCodes': station_code,
                                                   'collectTime': time})

    def get_dev_list(self, station_code) -> Dict:
        return self._request("getDevList", {'stationCodes': station_code})

    def get_dev_kpi_real(self, dev_id: str, dev_type_id: int) -> Dict:
        return self._request("getDevRealKpi",
                             {'devIds': dev_id, 'devTypeId': dev_type_id})

    def get_dev_kpi_fivemin(self, dev_id: str, dev_type_id: int,
                            date: pd.Timestamp) -> Dict:
        time = int(date.timestamp()) * 1000
        return self._request("getDevFiveMinutes",
                             {'devIds': dev_id, 'devTypeId': dev_type_id,
                              'collectTime': time})

    def get_dev_kpi_hour(self, dev_id: str, dev_type_id: int,
                         date: pd.Timestamp) -> Dict:
        time = int(date.timestamp()) * 1000
        return self._request("getDevKpiHour",
                             {'devIds': dev_id, 'devTypeId': dev_type_id,
                              'collectTime': time})

    def get_dev_kpi_day(self, dev_id: str, dev_type_id: int,
                        date: pd.Timestamp) -> Dict:
        time = int(date.timestamp()) * 1000
        return self._request("getDevKpiDay",
                             {'devIds': dev_id, 'devTypeId': dev_type_id,
                              'collectTime': time})

    def get_dev_kpi_month(self, dev_id: str, dev_type_id: int,
                          date: pd.Timestamp) -> Dict:
        time = int(date.timestamp()) * 1000
        return self._request("getDevKpiMonth",
                             {'devIds': dev_id, 'devTypeId': dev_type_id,
                              'collectTime': time})

    def get_dev_kpi_year(self, dev_id: str, dev_type_id: int,
                         date: pd.Timestamp) -> Dict:
        time = int(date.timestamp()) * 1000
        return self._request("getDevKpiYear",
                             {'devIds': dev_id, 'devTypeId': dev_type_id,
                              'collectTime': time})

    def dev_on_off(self, dev_id: str, dev_type_id: int,
                   control_type: int) -> Dict:
        # control_type
        # 1: power-on
        # 2: power-off
        return self._request("devOnOff",
                             {'devIds': dev_id, 'devTypeId': dev_type_id,
                              'controlType': control_type})

    def dev_upgrade(self, dev_id: str, dev_type_id: int) -> Dict:
        return self._request("devUpgrade",
                             {'devIds': dev_id, 'devTypeId': dev_type_id})

    def get_dev_upgradeinfo(self, dev_id: str, dev_type_id: int) -> Dict:
        return self._request("getDevUpgradeInfo",
                             {'devIds': dev_id, 'devTypeId': dev_type_id})


class PandasClient(Client):
    def get_kpi_day(self, station_code: str,
                    date: pd.Timestamp) -> pd.DataFrame:
        data = super(PandasClient, self).get_station_kpi_day(
            station_code=station_code, date=date)
        if len(data['data']) == 0:
            return pd.DataFrame()

        def flatten_data(j):
            for point in j['data']:
                line = {'collectTime': point['collectTime']}
                line.update(point['dataItemMap'])
                yield line

        df = pd.DataFrame(flatten_data(data))
        df['collectTime'] = pd.to_datetime(df['collectTime'], unit='ms',
                                           utc=True)
        df.set_index('collectTime', inplace=True)
        df = df.astype(float)
        return df
