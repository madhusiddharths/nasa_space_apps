"""The spending cap: disconnects the project from its billing account when the budget is used up.

Google Cloud has no setting that stops spending at an amount; a budget only sends messages.
This small function receives those messages (every 20 to 30 minutes, with the month's cost
so far) and, once the cost reaches the budget, takes billing off the project. Everything in
the project then stops, the app included, until someone links billing again by hand in the
console (Billing, Account management). Set up and tested as described in DEPLOY.md.

The cost figures reach the budget hours late, so the month can end somewhat over the amount.
"""
import base64
import json
import os

import functions_framework
from googleapiclient import discovery

PROJECT = os.environ["TARGET_PROJECT"]       # the project to disconnect


@functions_framework.cloud_event
def stop_billing(event):
    """Handles one budget message. A message with "dryRun": true only says what it would do
    (real budget messages never carry that field; it is for testing)."""
    message = json.loads(base64.b64decode(event.data["message"]["data"]))
    cost, budget = message["costAmount"], message["budgetAmount"]
    if cost < budget:
        print(f"Cost so far {cost} is under the budget of {budget}. Nothing to do.")
        return

    billing = discovery.build("cloudbilling", "v1", cache_discovery=False)
    name = f"projects/{PROJECT}"
    if not billing.projects().getBillingInfo(name=name).execute().get("billingEnabled"):
        print(f"Cost {cost} has reached the budget of {budget}; billing is already off for {PROJECT}.")
        return
    if message.get("dryRun"):
        print(f"DRY RUN: cost {cost} has reached the budget of {budget}; would take billing off {PROJECT}.")
        return
    billing.projects().updateBillingInfo(name=name, body={"billingAccountName": ""}).execute()
    print(f"Cost {cost} has reached the budget of {budget}. Billing is now OFF for {PROJECT}.")
