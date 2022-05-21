import os
import json
import datetime
import requests
import logging

from bs4 import BeautifulSoup, SoupStrainer # noqa

from google.cloud import pubsub_v1


project_id = os.environ["GCP_PROJECT"]
publisher = pubsub_v1.PublisherClient()


def check_updates_in_folder_with_folders(start_folder_num):
    """Check if there are changes in folder that contain other folders"""

    last_folder_update = datetime.datetime(1, 1, 1, 0, 0)
    page_summary = []

    if not start_folder_num:
        url = 'https://lizaalert.org/forum/index.php'
    else:
        url = 'https://lizaalert.org/forum/viewforum.php?f=' + str(start_folder_num)

    try:
        r = requests.Session().get(url, timeout=20)  # timeout is req'd to mitigate daily night forum update

        only_tag = SoupStrainer('div', {'class': 'forabg'})
        soup = BeautifulSoup(r.content, features='lxml', parse_only=only_tag)
        del r  # trying to free up memory
        search_code_blocks = soup.find_all('div', {'class': 'forabg'})
        del soup  # trying to free up memory

        # if we parse the main page - we're interested in the first 3 blocks only
        if not start_folder_num:
            # block with archive folders
            temp_block = search_code_blocks[-2]
            # first 2 blocks (sometimes it's, surprisingly, 3)
            search_code_blocks = search_code_blocks[0:3]
            # final list is: 1st, 2nd and pre-last blocks
            search_code_blocks.append(temp_block)

    except Exception as e1:
        logging.info(f'Checking topics by update time in folder {start_folder_num} triggered an error')
        logging.exception(e1)
        search_code_blocks = None

    try:
        if search_code_blocks:
            for block in search_code_blocks:

                folders = block.find_all('li', {'class': 'row'})
                for folder in folders:

                    # found no cases where there can be more than 1 topic name or date, so find i/o find_all is used
                    folder_num_str = folder.find('a', {'class': 'forumtitle'})['href']

                    start_symb_to_del = folder_num_str.find('&sid=')
                    if start_symb_to_del != -1:
                        folder_num = int(folder_num_str[18:start_symb_to_del])
                    else:
                        folder_num = int(folder_num_str[18:])

                    folder_time_str = folder.find('time')['datetime']
                    folder_time = datetime.datetime.strptime(folder_time_str, '%Y-%m-%dT%H:%M:%S+00:00')

                    # remove useless folders: Справочники, Снаряжение, Постскриптум and all from Обучение и Тренировки
                    if folder_num not in {84, 113, 112, 270, 86, 87, 88, 165, 365, 89, 172, 91, 90}:

                        page_summary.append([folder_num, folder_time_str, folder_time])

                        if last_folder_update < folder_time:
                            last_folder_update = folder_time

    except Exception as e2:
        logging.info(f'composing the topics\' page summaries fired an error, mother-folder {start_folder_num}')
        logging.exception(e2)

    return page_summary, last_folder_update


def time_delta(now, time):
    """provides a difference in minutes for 2 datetimes"""

    time_diff = now - time
    time_diff_in_min = (time_diff.days * 24 * 60) + (time_diff.seconds // 60)

    return time_diff_in_min


def get_the_list_folders_to_update(list_of_folders_and_times, now_time, delay_time):
    """get the list of updated folders that were updated recently"""

    list_of_updated_folders = []

    for line in list_of_folders_and_times:
        f_num, f_time_str, f_time = line
        time_diff_in_min = time_delta(now_time, f_time)

        if time_diff_in_min <= delay_time:
            list_of_updated_folders.append(f_num)

    return list_of_updated_folders


def publish_to_pubsub(message):
    """publish a pub/sub message"""

    global project_id
    global publisher

    # Prepare to turn to the existing pub/sub topic
    topic_name = 'topic_update_identified'
    topic_path = publisher.topic_path(project_id, topic_name)

    # Prepare the message
    message_json = json.dumps({'data': {'message': message}, })
    message_bytes = message_json.encode('utf-8')

    # Publish a message
    try:
        publish_future = publisher.publish(topic_path, data=message_bytes)
        publish_future.result()  # Verify the publish succeeded

    except Exception as e:
        logging.info('Pub/sub message was NOT published, fired an error')
        logging.exception(e)

    return None


def main(event, context): # noqa
    """main function that starts first"""

    global project_id
    global publisher

    now = datetime.datetime.now()
    folder_num_to_check = None

    list_of_folders_and_times, last_update_time = check_updates_in_folder_with_folders(folder_num_to_check)

    time_diff_in_min = time_delta(now, last_update_time)

    if last_update_time != datetime.datetime(1, 1, 1, 0, 0):
        logging.info(f'{str(time_diff_in_min)} minute(s) ago forum was updated')
    else:
        logging.info('no info on when forum was updated')

    # next actions only if the forum update happened within the defined period (2-3 minutes, defined in "delay")
    delay = 2  # minutes

    if time_diff_in_min <= delay:

        list_of_updated_folders = get_the_list_folders_to_update(list_of_folders_and_times, now, delay)
        logging.info(f'Folders with new info WITHOUT snapshot checks: {str(list_of_updated_folders)}')

        list_for_pubsub = []
        for line in list_of_folders_and_times:
            list_for_pubsub.append([line[0], line[1]])

        publish_to_pubsub(str(list_for_pubsub))

    return None
