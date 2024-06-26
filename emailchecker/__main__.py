import time
from os import getenv

from dotenv import load_dotenv

from slack_sdk.webhook import WebhookClient

from lemmylib.lib import LemmyLib

from emailchecker import fetchLists

from psycopg2.extensions import connection
import psycopg2 as pg

load_dotenv()

disposable_emails = []

config = {
    'LEMMY_URL': getenv('LEMMY_URL'),
    'LEMMY_USERNAME': getenv('LEMMY_USERNAME'),
    'LEMMY_PASSWORD': getenv('LEMMY_PASSWORD'),
    'SLACK_WEBHOOK_URL': getenv('SLACK_WEBHOOK_URL'),
    "SEARCH_DELAY_SECONDS": getenv("SEARCH_DELAY_SECONDS"),
    'DB_NAME': getenv('DB_NAME'),
    'DB_USER': getenv('DB_USER'),
    'DB_PASSWORD': getenv('DB_PASSWORD'),
    'DB_HOST': getenv('DB_HOST'),
    'DB_PORT': getenv('DB_PORT'),
    'DENY_TRASH_MAILS': getenv('DENY_TRASH_MAILS'),
    'LOCAL_USER_TABLE': getenv('LEMMY_LOCAL_USER_TABLE'),
    'REGISTRATION_APPLICATION_TABLE': getenv('LEMMY_REGISTRATION_APPLICATION_TABLE'),
    'PERSON_TABLE': getenv('LEMMY_PERSON_TABLE'),
}

webhook = False
if config.get("SLACK_WEBHOOK_URL", None) is not None and config.get("SLACK_WEBHOOK_URL", None) != "":
    webhook = WebhookClient(config.get("SLACK_WEBHOOK_URL"))

lemmy = LemmyLib(config.get("LEMMY_URL"))
lemmy.login(config.get("LEMMY_USERNAME"), config.get("LEMMY_PASSWORD"))


def get_connection():
    return pg.connect(
        dbname=config['DB_NAME'],
        user=config['DB_USER'],
        password=config['DB_PASSWORD'],
        host=config['DB_HOST'],
        port=config['DB_PORT']
    )


def check_answer(answer: str | None) -> bool:
    return answer is not None and (
        answer.strip().upper() == "I AGREE TO THE TOS" or answer.strip().upper() == "I AGREE TO THE TERMS OF SERVICE")


def fetch_registrations():
    registrations = []
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT a.id, l.id, l.email, a.answer, l.person_id, p.name FROM {config.get('REGISTRATION_APPLICATION_TABLE')} a JOIN {config.get('LOCAL_USER_TABLE')} l ON l.id = a.local_user_id JOIN {config.get('PERSON_TABLE')} p ON p.id = l.person_id WHERE a.admin_id IS NULL and l.email_verified = true AND l.accepted_application = false ORDER BY a.id DESC LIMIT 10")
            for row in cur.fetchall():
                registrations.append({
                    "registration_application": {
                        "id": row[0],
                        "answer": str(row[3])
                    },
                    "creator_local_user": {
                        "id": row[1],
                        "email": str(row[2]),
                    },
                    "creator": {
                        "id": row[4],
                        "name": str(row[5])
                    }
                })
    return registrations


def purge_user(user_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {config.get('PERSON_TABLE')} WHERE id = %s", (user_id,))
            conn.commit()
            return


def main():
    global disposable_emails
    fetchLists.run()
    print("Preparing emails....")
    with open("./emailchecker/disposable.list", "r") as file:
        disposable_emails = file.read().splitlines()
    print("Done preparing emails")
    while True:
        print("Checking for new registrations")
        try:
            registrations = fetch_registrations()
            print("Found " + str(len(registrations)) + " registrations")
            for registration in registrations:
                try:
                    if registration["creator_local_user"] is None or "email" not in \
                        registration["creator_local_user"]:
                        continue
                    local_user = registration["creator_local_user"]

                    email_to_check = registration["creator_local_user"]["email"] if registration[
                                                                                        "creator_local_user"] is not None and "email" in \
                                                                                    registration[
                                                                                        "creator_local_user"] else "test@gmx.net"
                    domain: str = email_to_check.split("@")[1]
                    user = registration["creator"]

                    if not check_answer(registration["registration_application"]["answer"]):
                        lemmy.approve_registration_application(registration["registration_application"]["id"],
                                                               approve=False)

                        purge_user(user["id"])
                        # lemmy.purge_person(user["id"], "User did not agree to the terms of service.")
                        if webhook:
                            webhook.send(
                                text=f"User {user['name']} got blocked for not agreeing to the terms of service.")
                        continue

                    print("Checking " + domain)
                    if domain.strip() in disposable_emails:
                        print(
                            f"User {user['name']} got blocked for using a disposable email address ({email_to_check})")
                        if getenv("DENY_TRASH_MAILS") == "true":
                            lemmy.approve_registration_application(registration["registration_application"]["id"],
                                                                   False)
                            purge_user(user["id"])
                            # lemmy.purge_person(user["id"], "User used a disposable email address.")

                        if webhook:
                            webhook.send(text=f"User {user['name']} got blocked for using a disposable email address")
                    else:
                        lemmy.approve_registration_application(registration["registration_application"]["id"], True)
                        if webhook:
                            webhook.send(text=f"User {user['name']} got approved.")

                except Exception as e:
                    print("Error while checking for one registration")
                    print(e)
        except Exception as e:
            print("Error while checking for new registrations")
            print(e)

        print(f"Waiting for {config.get('SEARCH_DELAY_SECONDS', 60)} Seconds...")
        time.sleep(int(config.get("SEARCH_DELAY_SECONDS", 60)))


if __name__ == "__main__":
    main()
