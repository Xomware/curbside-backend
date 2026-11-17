from __future__ import annotations

from conftest import call

from lambdas.common.households import create_household
from lambdas.common.models import HouseholdCreate
from lambdas.households_delete.handler import handler


def test_deletes_household_children_and_notes_only(table, account, map_id, hh_id):
    pk = f"MAP#{map_id}"
    other = create_household(map_id, HouseholdCreate(label="Other", lat=1, lng=1))["id"]
    for i in range(15):
        table.put_item(Item={"pk": pk, "sk": f"HH#{hh_id}#PERSON#{i:02d}"})
        table.put_item(Item={"pk": pk, "sk": f"NOTE#{hh_id}#{i:02d}"})
    table.put_item(Item={"pk": pk, "sk": f"NOTE#{other}#01"})

    status, body = call(handler, path={"mapId": map_id, "hhId": hh_id})

    assert (status, body["data"]) == (200, {"id": hh_id})
    left = {i["sk"] for i in table.scan()["Items"] if i["pk"] == pk}
    assert left == {"META", f"MEMBER#{account}", f"HH#{other}", f"NOTE#{other}#01"}


def test_missing_household_is_404(table, map_id):
    status, body = call(handler, path={"mapId": map_id, "hhId": "0" * 26})
    assert (status, body["error"]["code"]) == (404, "household_not_found")
