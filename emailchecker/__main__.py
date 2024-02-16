import time
from os import getenv
from typing import List

from dotenv import load_dotenv

from slack_sdk.webhook import WebhookClient

from lemmylib.lib import LemmyLib

from emailchecker import fetchLists

load_dotenv()

lemmy = LemmyLib(getenv("LEMMY_URL"))
lemmy.login(getenv("LEMMY_USERNAME"), getenv("LEMMY_PASSWORD"))

disposable_emails = []

webhook = False
if getenv("SLACK_WEBHOOK_URL") != "":
    webhook = WebhookClient(getenv("SLACK_WEBHOOK_URL"))


def check_answer(answer: str | None) -> bool:
    return answer is not None and (
        answer.strip().upper() == "I AGREE TO THE TOS" or answer.strip().upper() == "I AGREE TO THE TERMS OF SERVICE")


def fetch_registrations():
    registrations = []
    for i in range(1, 5):
        print("Fetching page " + str(i))
        registration = lemmy.list_registration_applications(page=i, unread_only=True)
        registrations = registrations + registration.json()["registration_applications"]

    return registrations


def main():
    global disposable_emails
    print("Preparing emails....")
    with open("./emailchecker/disposable.list", "r") as file:
        disposable_emails = file.read().splitlines()
    print("Done preparing emails")
    while True:
        print("Checking for new registrations")
        try:
            registrations = fetch_registrations()
            print("Found " + str(len(registrations)) + " registrations"
                  )
            for registration in registrations:
                try:
                    if "admin" in registration or registration["creator_local_user"] is None or "email" not in \
                        registration["creator_local_user"]:
                        continue
                    local_user = registration["creator_local_user"]

                    email_to_check = registration["creator_local_user"]["email"] if registration[
                                                                                        "creator_local_user"] is not None and "email" in \
                                                                                    registration[
                                                                                        "creator_local_user"] else "test@gmx.net"
                    domain: str = email_to_check.split("@")[1]
                    user = registration["creator"]

                    if local_user is not None and local_user["email_verified"] is False:
                        continue

                    if not check_answer(registration["registration_application"]["answer"]):
                        lemmy.approve_registration_application(registration["registration_application"]["id"],
                                                               approve=False)

                        lemmy.purge_person(user["id"], "Did not agree to the terms of service.")
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
                            lemmy.purge_person(user["id"], "Used a trash mail.")

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

        print("Waiting for 60 Seconds...")
        time.sleep(60)


def run():
    fetchLists.run()
    main()


if __name__ == "__main__":
    run()
