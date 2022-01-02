from flask import Flask, render_template, request, jsonify
import json
import os.path
import os
import asyncio
import aiohttp
# import aiofiles  # pip install aiofiles
import requests
import zipfile
import io
import pandas as pd
import urllib.parse
import time
# import nest_asyncio
# nest_asyncio.apply()

app = Flask(__name__)
app.debug = True


class Accessibility:
    def __init__(self):
        self.__accessibility_dict = None

    @property
    def accessibility_dict(self):
        return self.__accessibility_dict

    # @property
    # def avg_accessibility(self):
    #     return self.__avg_accessibility

    # @property
    # def summer_accessibility(self):
    #     return self.__summer_accessibility

    @accessibility_dict.setter
    def accessibility_dict(self, value):
        self.__accessibility_dict = value

    # @avg_accessibility.setter
    # def avg_accessibility(self, value):
    #     self.__avg_accessibility = value

    # @summer_accessibility.setter
    # def summer_accessibility(self, value):
    #     self.__summer_accessibility = value


accessibility = Accessibility()

# accessibility_dict = None
# avg_accessibility = None
# summer_accessibility = None


"""
async function to fetch and download zip file
Unzip the file and save to data folder. 
If the users' selected location does not have data, raise error.
"""


def download_esox_data(lat, lon):
    url = f'https://lau-sda.azurewebsites.net/api/download?code=5KThUDySpkOguD6BIKpP820FjObFwBHZ0QuEMHFjELXSWtPdrQBC4A==&container=esoxera5&location=n{lat}_e{lon}&onlyData=true'
    print(url)
    req = requests.get(url)
    if req.ok:
        z = zipfile.ZipFile(io.BytesIO(req.content))
        return z.extractall("./data")
    else:
        print('HTTP/1.1 404 Not Found\r\n')
        print('Content-Type: text/html\r\n\r\n')
        print('<html><head></head><body><h1>404 Not Found</h1></body></html>')
    # if req.status == 200:
    # response = req.read()
    # z = zipfile.Zipfile(io.BytesIO(req.content))
    # print('downloaded?')
    # return z.extractall("./data")

    # with aiohttp.ClientSession() as client:
    #     try:
    #         with client.get(url) as resp:
    #             if resp.status == 200:
    #                 response = resp.read()
    #                 z = zipfile.ZipFile(io.BytesIO(response))
    #                 return z.extractall("./data")
    #             else:
    #                 print(resp.status)
    #                 print("selected location is not a potential site")
    #                 raise SystemExit(2)
    #     except aiohttp.ClientConnectorError as e:
    #         print('Connection Error', str(e))

    # z = zipfile.ZipFile(io.BytesIO(response))
    # return z.extractall("./data")


"""
Take the downloaded weather data and call calculate_accessbility()
Firstly, check if the file exists to the coordinates
If not, download first, and then calculate
Return the monthly accessibility in dictionary
"""


def calculate(lat, lon):
    if os.path.isfile(f'./data/n{"{:.2f}".format(float(lat))}_e{"{:.2f}".format(float(lon))}.csv'):
        print("Start Calculating....")
        pd.options.mode.chained_assignment = None  # default='warn'
        df = pd.DataFrame()
        file_address = f'./data/n{lat}_e{lon}.csv'
        df = pd.read_csv(file_address, skiprows=5)

        # change column names for readability and code easiness
        cols = ['timestamp', '10m', '100m', 'hs', 'tp']
        df.columns = cols

        # Change timestamp's datatypes to datetime
        df['timestamp'] = pd.to_datetime(df['timestamp'])

        # Extracting year, month, and hour from the timestamp
        df['year'] = df['timestamp'].dt.year
        df['month'] = df['timestamp'].dt.month
        df['hour'] = df['timestamp'].dt.hour

        df = df[df['year'] <= 1994]
        df.describe()

        hub_height = 105
        measurement_height = 10
        wind_profile_power_law_coeff = 0.07

        df['wind_speed_hub_height'] = df['10m'] * \
            (hub_height / measurement_height)**wind_profile_power_law_coeff

        ##### Change these parameters if necessary!!! #####
        ctv_max_wave_height = 1.5
        ctv_max_wind_speed = 100
        ctv_ww_start = 7
        ctv_ww_end = 19
        ctv_max_day_length = ctv_ww_end - ctv_ww_start
        ctv_min_day_length = 12
        ################################################

        """
        CTV can access when the following conditions are met.
        - hs is smaller than ctv_max_wave_height (1.5m)
        - wind_speed_hub_height is smaller than ctv_max_wind_speed (100 (m/s))
        - hour is after ctv_ww_start (7am)
        - hour is before ctv_ww_end (7pm)

        Assign 1 once all these conditions are met.

        Loop through each row and if the value is 1 (conditions are met), you add 1 to the value from the previous cell.
        (Iterating rows with .loc is very inefficient computing, but this seems to be the only way to achive the same result with the excel formula)
        """

        def ctv_conditions(s):  # Max CTV WW duration (Column J)
            if(s['hs'] < ctv_max_wave_height) and (s['wind_speed_hub_height'] < ctv_max_wind_speed) and (s['hour'] >= ctv_ww_start) and (s['hour'] < ctv_ww_end):
                return 1
            else:
                return 0

        df['max_ctv_ww_duration'] = df.apply(ctv_conditions, axis=1)

        for i in range(1, len(df)):
            if df.loc[i, 'max_ctv_ww_duration'] == 1:
                df.loc[i, 'max_ctv_ww_duration'] = df.loc[i -
                                                          1, 'max_ctv_ww_duration'] + 1

        """
        Based on max_ctv_ww_duration, you need to evaluate if you can access the site with CTV (1: YES, 0: NO)

        The conditions to meet are as below:
        - If it is ctv_ww_start(7am),
            See max_ctv_ww_duration column for the next 12 rows including 7am, equivalent to ctv_max_day_length.
        - AND if MAX of max_ctv_ww_duration is bigger or equal to ctv_min_day_length (12), THEN assign 1 (access).

        - ELSE if, it is after ctv_ww_start, 11am for instance,
        - AND if it is before ctv_ww_end,
        - AND if one hour ago (10am) was also accessible (marked 1), THEN assign 1 (access).

        - OTHERWISE, it is NOT accessible (marked 0)

        """

        # Column N (Identification of CTV access hours (1=access))
        df['ctv_access'] = df['max_ctv_ww_duration']

        for i in range(1, len(df)):
            if df.loc[i, 'hour'] == ctv_ww_start:
                min = ctv_min_day_length

                for j in range(1, ctv_max_day_length):
                    if df.loc[i+j, 'max_ctv_ww_duration'] >= min:
                        df.loc[i, 'ctv_access'] = 1

            elif (df.loc[i, 'hour'] > ctv_ww_start) and (df.loc[i, 'hour'] < ctv_ww_end) and (df.loc[i-1, 'ctv_access'] == 1):
                df.loc[i, 'ctv_access'] = 1

            else:
                df.loc[i, 'ctv_access'] = 0

        mon = {'month': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], 'month_days': [
            31, 28.3, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]}
        month = pd.DataFrame(data=mon)
        month

        df = pd.merge(df, month, on='month')

        def monthly_ctv_access(dff):
            mon_access = {}

            for i in range(1, 13):  # Column APm CTV access
                # Filter a month (e.g. January == 1)
                dff = df[df['month'] == i]
                # Add up the value (identification of CTV access hours (1=access))
                total = dff['ctv_access'].sum()
                # month days * max_day_length
                divided_by = 5 * dff['month_days'].mean() * ctv_max_day_length
                rate = round(total / divided_by, 2) * 100
                mon_access[i] = rate

            return mon_access

        ctv_monthly = monthly_ctv_access(df)
        accessibility.accessibility_dict = ctv_monthly
        print(ctv_monthly)
        return ctv_monthly
    else:

        # loop = asyncio.new_event_loop()
        # # loop = asyncio.get_event_loop()
        # asyncio.set_event_loop(loop)
        try:
            # loop.run_until_complete(download_esox_data(
            #     "{:.2f}".format(float(lat)), "{:.2f}".format(float(lon))))
            download_esox_data(lat, lon)
            pd.options.mode.chained_assignment = None  # default='warn'
            df = pd.DataFrame()
            file_address = f'./data/n{lat}_e{lon}.csv'
            df = pd.read_csv(file_address, skiprows=5)

            # change column names for readability and code easiness
            cols = ['timestamp', '10m', '100m', 'hs', 'tp']
            df.columns = cols

            # Change timestamp's datatypes to datetime
            df['timestamp'] = pd.to_datetime(df['timestamp'])

            # Extracting year, month, and hour from the timestamp
            df['year'] = df['timestamp'].dt.year
            df['month'] = df['timestamp'].dt.month
            df['hour'] = df['timestamp'].dt.hour

            df = df[df['year'] <= 1994]
            df.describe()

            hub_height = 105
            measurement_height = 10
            wind_profile_power_law_coeff = 0.07

            df['wind_speed_hub_height'] = df['10m'] * \
                (hub_height / measurement_height)**wind_profile_power_law_coeff

            ##### Change these parameters if necessary!!! #####
            ctv_max_wave_height = 1.5
            ctv_max_wind_speed = 100
            ctv_ww_start = 7
            ctv_ww_end = 19
            ctv_max_day_length = ctv_ww_end - ctv_ww_start
            ctv_min_day_length = 12
            ################################################

            """
            CTV can access when the following conditions are met.
            - hs is smaller than ctv_max_wave_height (1.5m)
            - wind_speed_hub_height is smaller than ctv_max_wind_speed (100 (m/s))
            - hour is after ctv_ww_start (7am)
            - hour is before ctv_ww_end (7pm)

            Assign 1 once all these conditions are met.

            Loop through each row and if the value is 1 (conditions are met), you add 1 to the value from the previous cell.
            (Iterating rows with .loc is very inefficient computing, but this seems to be the only way to achive the same result with the excel formula)
            """

            def ctv_conditions(s):  # Max CTV WW duration (Column J)
                if(s['hs'] < ctv_max_wave_height) and (s['wind_speed_hub_height'] < ctv_max_wind_speed) and (s['hour'] >= ctv_ww_start) and (s['hour'] < ctv_ww_end):
                    return 1
                else:
                    return 0

            df['max_ctv_ww_duration'] = df.apply(ctv_conditions, axis=1)

            for i in range(1, len(df)):
                if df.loc[i, 'max_ctv_ww_duration'] == 1:
                    df.loc[i, 'max_ctv_ww_duration'] = df.loc[i -
                                                              1, 'max_ctv_ww_duration'] + 1

            """
            Based on max_ctv_ww_duration, you need to evaluate if you can access the site with CTV (1: YES, 0: NO)

            The conditions to meet are as below:
            - If it is ctv_ww_start(7am),
                See max_ctv_ww_duration column for the next 12 rows including 7am, equivalent to ctv_max_day_length.
            - AND if MAX of max_ctv_ww_duration is bigger or equal to ctv_min_day_length (12), THEN assign 1 (access).

            - ELSE if, it is after ctv_ww_start, 11am for instance,
            - AND if it is before ctv_ww_end,
            - AND if one hour ago (10am) was also accessible (marked 1), THEN assign 1 (access).

            - OTHERWISE, it is NOT accessible (marked 0)

            """

            # Column N (Identification of CTV access hours (1=access))
            df['ctv_access'] = df['max_ctv_ww_duration']

            for i in range(1, len(df)):
                if df.loc[i, 'hour'] == ctv_ww_start:
                    min = ctv_min_day_length

                    for j in range(1, ctv_max_day_length):
                        if df.loc[i+j, 'max_ctv_ww_duration'] >= min:
                            df.loc[i, 'ctv_access'] = 1

                elif (df.loc[i, 'hour'] > ctv_ww_start) and (df.loc[i, 'hour'] < ctv_ww_end) and (df.loc[i-1, 'ctv_access'] == 1):
                    df.loc[i, 'ctv_access'] = 1

                else:
                    df.loc[i, 'ctv_access'] = 0

            mon = {'month': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], 'month_days': [
                31, 28.3, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]}
            month = pd.DataFrame(data=mon)
            month

            df = pd.merge(df, month, on='month')

            def monthly_ctv_access(dff):
                mon_access = {}

                for i in range(1, 13):  # Column APm CTV access
                    # Filter a month (e.g. January == 1)
                    dff = df[df['month'] == i]
                    # Add up the value (identification of CTV access hours (1=access))
                    total = dff['ctv_access'].sum()
                    # month days * max_day_length
                    divided_by = 5 * \
                        dff['month_days'].mean() * ctv_max_day_length
                    rate = round(total / divided_by, 2) * 100
                    mon_access[i] = rate

                return mon_access

            ctv_monthly = monthly_ctv_access(df)
            accessibility.accessibility_dict = ctv_monthly
            print(ctv_monthly)
            return ctv_monthly
        except SystemExit:
            print('does not have file')
            return 'error'  # From the browser handling the error by showing message such as "The selected location is not possible for .."
        # finally:
        #     loop.close()


"""
The function is calculating accessibility
And return monthly accessibility [Jan: 23, Feb:30 ....]
Reduce to five years of weather data 

"""


# async def calculate_accessibility(lat, lon):
#     pd.options.mode.chained_assignment = None  # default='warn'
#     df = pd.DataFrame()
#     file_address = f'./data/n{lat}_e{lon}.csv'
#     df = pd.read_csv(file_address, skiprows=5)

#     # change column names for readability and code easiness
#     cols = ['timestamp', '10m', '100m', 'hs', 'tp']
#     df.columns = cols

#     # Change timestamp's datatypes to datetime
#     df['timestamp'] = pd.to_datetime(df['timestamp'])
#     df.dtypes

#     # Extracting year, month, and hour from the timestamp
#     df['year'] = df['timestamp'].dt.year
#     df['month'] = df['timestamp'].dt.month
#     df['hour'] = df['timestamp'].dt.hour

#     df = df[df['year'] <= 1994]
#     df.describe()

#     hub_height = 105
#     measurement_height = 10
#     wind_profile_power_law_coeff = 0.07

#     df['wind_speed_hub_height'] = df['10m'] * \
#         (hub_height / measurement_height)**wind_profile_power_law_coeff

#     ##### Change these parameters if necessary!!! #####
#     ctv_max_wave_height = 1.5
#     ctv_max_wind_speed = 100
#     ctv_ww_start = 7
#     ctv_ww_end = 19
#     ctv_max_day_length = ctv_ww_end - ctv_ww_start
#     ctv_min_day_length = 12
#     ################################################

#     """
#     CTV can access when the following conditions are met.
#     - hs is smaller than ctv_max_wave_height (1.5m)
#     - wind_speed_hub_height is smaller than ctv_max_wind_speed (100 (m/s))
#     - hour is after ctv_ww_start (7am)
#     - hour is before ctv_ww_end (7pm)

#     Assign 1 once all these conditions are met.

#     Loop through each row and if the value is 1 (conditions are met), you add 1 to the value from the previous cell.
#     (Iterating rows with .loc is very inefficient computing, but this seems to be the only way to achive the same result with the excel formula)
#     """

#     def ctv_conditions(s):  # Max CTV WW duration (Column J)
#         if(s['hs'] < ctv_max_wave_height) and (s['wind_speed_hub_height'] < ctv_max_wind_speed) and (s['hour'] >= ctv_ww_start) and (s['hour'] < ctv_ww_end):
#             return 1
#         else:
#             return 0

#     df['max_ctv_ww_duration'] = df.apply(ctv_conditions, axis=1)

#     for i in range(1, len(df)):
#         if df.loc[i, 'max_ctv_ww_duration'] == 1:
#             df.loc[i, 'max_ctv_ww_duration'] = df.loc[i -
#                                                       1, 'max_ctv_ww_duration'] + 1

#     """
#     Based on max_ctv_ww_duration, you need to evaluate if you can access the site with CTV (1: YES, 0: NO)

#     The conditions to meet are as below:
#     - If it is ctv_ww_start(7am),
#         See max_ctv_ww_duration column for the next 12 rows including 7am, equivalent to ctv_max_day_length.
#     - AND if MAX of max_ctv_ww_duration is bigger or equal to ctv_min_day_length (12), THEN assign 1 (access).

#     - ELSE if, it is after ctv_ww_start, 11am for instance,
#     - AND if it is before ctv_ww_end,
#     - AND if one hour ago (10am) was also accessible (marked 1), THEN assign 1 (access).

#     - OTHERWISE, it is NOT accessible (marked 0)

#     """

#     # Column N (Identification of CTV access hours (1=access))
#     df['ctv_access'] = df['max_ctv_ww_duration']

#     for i in range(1, len(df)):
#         if df.loc[i, 'hour'] == ctv_ww_start:
#             min = ctv_min_day_length

#             for j in range(1, ctv_max_day_length):
#                 if df.loc[i+j, 'max_ctv_ww_duration'] >= min:
#                     df.loc[i, 'ctv_access'] = 1

#         elif (df.loc[i, 'hour'] > ctv_ww_start) and (df.loc[i, 'hour'] < ctv_ww_end) and (df.loc[i-1, 'ctv_access'] == 1):
#             df.loc[i, 'ctv_access'] = 1

#         else:
#             df.loc[i, 'ctv_access'] = 0

#     mon = {'month': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], 'month_days': [
#         31, 28.3, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]}
#     month = pd.DataFrame(data=mon)
#     month

#     df = pd.merge(df, month, on='month')

#     def monthly_ctv_access(dff):
#         mon_access = {}

#         for i in range(1, 13):  # Column APm CTV access
#             dff = df[df['month'] == i]  # Filter a month (e.g. January == 1)
#             # Add up the value (identification of CTV access hours (1=access))
#             total = dff['ctv_access'].sum()
#             # month days * max_day_length
#             divided_by = 5 * dff['month_days'].mean() * ctv_max_day_length
#             rate = round(total / divided_by, 2) * 100
#             mon_access[i] = rate

#         return mon_access

#     ctv_monthly = monthly_ctv_access(df)

#     # values extracted using values()
#     # one-liner solution to problem.
#     # res = sum(ctv_monthly.values()) / len(ctv_monthly)
#     # printing result
#     # print("The yearly CTV accessibility : " + str(res))

#     # summer_res = (ctv_monthly[5]+ctv_monthly[6] + ctv_monthly[7]+ctv_monthly[8])/4

#     # print("The summer month's CTV accessibility : " + str(summer_res))
#     # print(ctv_monthly)

#     # ctv_monthly is dict of month&accessibility, res: average all year accessibility, summer_res: summer month accessibility.
#     return await ctv_monthly


# def caluclate_summer_accessibility(dict):
#     return (dict[4] + dict[5] + dict[6] + dict[7]) / 4


# def calculate_avg_accessibility(dict):
#     values = dict.values()
#     total = sum(values)
#     return total / 12


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/map')
def map():
    return render_template('map.html')


@app.route('/result')
def result():
    return render_template('result.html')


@app.route('/map_link')
def map_link():
    return render_template('map.html')


@app.route('/result/<string:siteLocation>', methods=['POST'])
def processSiteLocation(siteLocation):
    siteLocation = json.loads(siteLocation)
        # global siteCoord
        # siteCoord = siteLocation
        # calculate(55.25, -9.75)
    print()
    print('SITE LOCATION RECEIVED')
    print('----------------------')
    print(f"Longitude: {siteLocation['lng']}")
    print(f"Latitude: {siteLocation['lat']}")
        # asyncio.run(calculate(siteLocation['lat'], siteLocation['lng']))
    response = calculate(siteLocation['lat'], siteLocation['lng'])
    return jsonify(response)
    # return render_template('loading.html', filename=siteLocation)


# @app.route('/result/<string:siteLocation>', methods=['POST', 'GET'])
# def result(siteLocation):
#     siteLocation = json.loads(siteLocation)
#     # global siteCoord
#     # siteCoord = siteLocation
#     # calculate(55.25, -9.75)
#     print()
#     print('SITE LOCATION RECEIVED')
#     print('----------------------')
#     print(f"Longitude: {siteLocation['lng']}")
#     print(f"Latitude: {siteLocation['lat']}")
#     # asyncio.run(calculate(siteLocation['lat'], siteLocation['lng']))
#     calculate(siteLocation['lat'], siteLocation['lng'])
#     return render_template('result.html')


# @app.route('/result/')
# def sendAccessibility():
#     accessibility = session.get("accessibility")

#     if accessibility:
#         return render_template('result.html', json_data=json.dumps(accessibility))
    
#     else:
#         return render_template('result.html', json_data=None)
    # if accessibility.accessibility_dict is not None:
    #     return render_template('result.html', avg_accessibility=accessibility.avg_accessibility, summer_accessibility=accessibility.summer_accessibility)


# def convert(input):
#     # Converts unicode to string
#     if isinstance(input, dict):
#         return {convert(key): convert(value) for key, value in input.iteritems()}
#     elif isinstance(input, list):
#         return [convert(element) for element in input]
#     elif isinstance(input, str):
#         return input.encode('utf-8')
#     else:
#         return input


# @app.route("/loading")
# def target():
#     # You could do any information passing here if you want (i.e Post or Get request)
#     some_data = "Here's some example data"
#     # urllib2 is used if you have fancy characters in your data like "+"," ", or "="
#     some_data = urllib.parse.quote(convert(some_data))
#     # This is where the loading screen will be.
#     # ( You don't have to pass data if you want, but if you do, make sure you have a matching variable in the html i.e {{my_data}} )
#     return render_template('loading.html', my_data=some_data)


# @app.route("/processing")
# def processing():
#     # This is where the time-consuming process can be.
#     data = "No data was passed"
#     # In this case, the data was passed as a get request as you can see at the bottom of the loading.html file
#     if request.args.to_dict(flat=False)['data'][0]:
#         data = str(request.args.to_dict(flat=False)['data'][0])
#     # This is where your time-consuming stuff can take place (sql queries, checking other apis, etc)
#     # To simulate something time-consuming, I've tested up to 100 seconds
#     time.sleep(10)
#     # You can return a success/fail page here or whatever logic you want
#     return render_template('success.html', passed_data=data)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=9374, use_reloader=False)
