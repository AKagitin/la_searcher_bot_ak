import base64

import json
import datetime
import logging
import urllib.request

import psycopg2

from google.cloud import pubsub_v1
from google.cloud import secretmanager


url = "http://metadata.google.internal/computeMetadata/v1/project/project-id"
req = urllib.request.Request(url)
req.add_header("Metadata-Flavor", "Google")
project_id = urllib.request.urlopen(req).read().decode()

publisher = pubsub_v1.PublisherClient()


def process_pubsub_message(event):
    """convert incoming pub/sub message into regular data"""

    # FIXME
    logging.info(f'RECEIVED EVENT {event}')
    # FIXME ^^^
    # receiving message text from pub/sub
    if 'data' in event:
        received_message_from_pubsub = base64.b64decode(event['data']).decode('utf-8')
        print(f'DECODED DATA from EVENT {received_message_from_pubsub}')
        try:
            received_message_from_pubsub.replace('null', 'None')
            encoded_to_ascii = eval(received_message_from_pubsub)
            data_in_ascii = encoded_to_ascii['data']
            message_in_ascii = data_in_ascii['message']
        except Exception as e:
            logging.exception(e)
            message_in_ascii = None

    else:
        received_message_from_pubsub = 'I cannot read message from pub/sub'
        message_in_ascii = None

    logging.info(f'received from pubsub {received_message_from_pubsub}')
    logging.info(f'message in ascii {message_in_ascii}')

    return message_in_ascii


def publish_to_pubsub(topic_name, message):
    """publishing a new message to pub/sub"""

    global project_id

    # Preparing to turn to the existing pub/sub topic
    # topic_name = 'topic_notify_admin'
    topic_path = publisher.topic_path(project_id, topic_name)
    # Preparing the message
    message_json = json.dumps({'data': {'message': message}, })
    message_bytes = message_json.encode('utf-8')
    # Publishes a message
    try:
        publish_future = publisher.publish(topic_path, data=message_bytes)
        publish_future.result()  # Verify the publishing succeeded
        logging.info('Pub/sub message published from User Management: ' + message)

    except Exception as e:
        logging.error('Publish to pub/sub from User Management failed: ' + repr(e))
        logging.exception(e)

    return None


def notify_admin(message):
    """send the pub/sub message to Debug to Admin"""

    publish_to_pubsub('topic_notify_admin', message)

    return None


def get_secrets(secret_request):
    """get secret from GCP Secret Manager"""

    name = f"projects/{project_id}/secrets/{secret_request}/versions/latest"
    client = secretmanager.SecretManagerServiceClient()

    response = client.access_secret_version(name=name)

    return response.payload.data.decode("UTF-8")


def sql_connect_by_psycopg2():
    """set the connection to psql via psycopg2"""

    db_user = get_secrets("cloud-postgres-username")
    db_pass = get_secrets("cloud-postgres-password")
    db_name = get_secrets("cloud-postgres-db-name")
    db_conn = get_secrets("cloud-postgres-connection-name")
    db_host = '/cloudsql/' + db_conn

    conn_psy = psycopg2.connect(host=db_host, dbname=db_name, user=db_user, password=db_pass)

    return conn_psy


def mark_up_onboarding_status_0():
    """marks up Onboarding step_id=0 for existing old users"""

    # set PSQL connection & cursor
    conn = sql_connect_by_psycopg2()
    cur = conn.cursor()

    # add the New User into table users
    cur.execute("""
                    WITH 
                        onb AS (
                            select user_id, MAX(step_id) AS onb_step 
                            from user_onboarding GROUP BY 1), 
                        step_1 AS (
                            select u.user_id, u.reg_date, o.onb_step, 
                            CASE WHEN u.reg_date<'2023-05-14 12:40:00.000000' THEN 'before' ELSE 'after' END reg_period 
                            FROM users as u 
                            LEFT JOIN onb AS o 
                            ON u.user_id=o.user_id), 
                        step_2 AS (
                            SELECT user_id 
                            FROM step_1 
                            WHERE reg_period='before' AND onb_step IS NULL), 
                        s0 AS (
                            select user_id, timestamp, message_text, MAX(timestamp) OVER (PARTITION BY user_id), 
                            CASE WHEN timestamp=(MAX(timestamp) OVER (PARTITION BY user_id)) THEN 1 ELSE 0 END AS check 
                            FROM dialogs 
                            WHERE author='user'), 
                        only_starters AS (
                            SELECT user_id, timestamp 
                            FROM s0 
                            WHERE s0.check=1 AND message_text='/start') 
                    
                    SELECT u.user_id 
                    FROM step_2 AS u 
                    LEFT JOIN only_starters AS o 
                    ON u.user_id=o.user_id 
                    WHERE o.user_id IS NOT NULL 
                    LIMIT 1;
                    ;""")
    conn.commit()
    user_id_to_update = cur.fetchone()[0]

    if user_id_to_update:
        logging.info(f'User {user_id_to_update}, will be assigned with onboarding pref_id=0')

        # save onboarding start
        cur.execute("""
                            INSERT INTO user_onboarding 
                            (user_id, step_name, step_id, timestamp) 
                            VALUES (%s, 'start', 0, '2023-05-14 12:39:00.000000')
                            ;""",
                    (user_id_to_update,))
        conn.commit()

    else:
        logging.info(f'There are no users to assign onboarding pref_id=0.')

    # close connection & cursor
    cur.close()
    conn.close()

    return None


def mark_up_onboarding_status_80():
    """marks up Onboarding step_id=80 for existing old users"""

    # set PSQL connection & cursor
    conn = sql_connect_by_psycopg2()
    cur = conn.cursor()

    # add the New User into table users
    cur.execute("""
                    select user_id 
                    from user_view 
                    where 
                        receives_summaries='yes' and 
                        notif_setting='yes' and 
                        onb_step is NULL and 
                        reg_period='before' 
                    limit 1;
                """)
    conn.commit()
    user_id_to_update = cur.fetchone()[0]

    if user_id_to_update:
        logging.info(f'User {user_id_to_update}, will be assigned with onboarding pref_id=80')

        # save onboarding start
        cur.execute("""
                            INSERT INTO user_onboarding 
                            (user_id, step_name, step_id, timestamp) 
                            VALUES (%s, 'finished', 80, '2023-05-14 12:39:00.000000')
                            ;""",
                    (user_id_to_update,))
        conn.commit()

    else:
        logging.info(f'There are no users to assign onboarding pref_id=80.')

    # close connection & cursor
    cur.close()
    conn.close()

    return None


def main(event, context): # noqa
    """main function"""

    try:
        mark_up_onboarding_status_0()
        mark_up_onboarding_status_80()

    except Exception as e:
        logging.error('User activation script failed')
        logging.exception(e)

    return 'ok'