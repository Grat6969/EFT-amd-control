"""Tarkov's story chapters (1.0 and later), which tarkov.dev's quest data
doesn't include.

Kept by hand from community guides (TarkovForge's story guide and the wiki),
so it can lag behind a game patch: check the game when a step doesn't match.
Each step has a fixed id; your ticks are stored against those ids (see
progress.py, "story"), so rewording a step keeps them.

Step fields: id, text, map (None = trader menu / hideout), need (what to
bring or have), optional, branch (only on some routes).
"""

from __future__ import annotations

from typing import Dict, List, Optional

SOURCE = "TarkovForge story guide and the Escape from Tarkov wiki (November 2026)"
SOURCE_URL = "https://tarkovforge.com/story-guide"


def _steps(prefix: str, rows: List[tuple]) -> List[dict]:
    out = []
    for n, row in enumerate(rows, 1):
        text, map_, need = row[0], row[1], row[2]
        flags = row[3] if len(row) > 3 else ""
        branch = row[4] if len(row) > 4 else None
        out.append({"id": f"{prefix}-{n:02d}", "text": text, "map": map_, "need": need,
                    "optional": "opt" in flags, "branch": branch})
    return out


CHAPTERS: List[dict] = [
    {
        "id": "tour", "name": "Tour", "kind": "main",
        "start": "Automatic on a new character, in the Ground Zero tutorial raid.",
        "summary": "Opens the traders and the maps one by one, ending in The Lab.",
        "steps": _steps("tour", [
            ("Escape Ground Zero (extract behind SkySide)", "Ground Zero", ""),
            ("Talk to Therapist", None, ""),
            ("Get access to Streets of Tarkov", "Streets of Tarkov", ""),
            ("Pay Therapist 250,000 roubles (skipping leaves Streets locked)", None, "250,000 ₽", "opt"),
            ("Get access to Interchange: extract Survived/Run Through, or visit 3 times (unlocks Skier)", "Interchange", ""),
            ("Get access to Customs: extract Survived/Run Through, or visit 3 times", "Customs", ""),
            ("Give Skier 5 found-in-raid building materials or tools at once (unlocks Mechanic and Factory)", None, "5 FiR building materials/tools"),
            ("Get access to Factory: extract Survived/Run Through, or visit 3 times", "Factory", ""),
            ("Give Mechanic 2 found-in-raid weapons (unlocks Prapor and Woods)", None, "2 FiR weapons"),
            ("Get access to Woods: 3 kills, and extract Survived/Run Through or visit 3 times (unlocks Peacekeeper, Shoreline)", "Woods", ""),
            ("Use the intercom in Shoreline's south-east corner, then survive and extract (don't shoot the guards)", "Shoreline", ""),
            ("Give Prapor 5 PMC dogtags (unlocks Reserve; looted tags count)", None, "5 PMC dogtags", "opt"),
            ("Pay Mechanic in dollars to unlock Lighthouse (guides disagree on $8,000 vs more: check in game)", None, "Dollars", "opt"),
            ("Transit into The Lab from Streets or Factory", "The Lab", "TerraGroup Labs access keycard"),
            ("Search the top management offices (O21, second level)", "The Lab", ""),
            ("Search the server room (first level, by the hangar)", "The Lab", ""),
            ("Find the drainage escape path at the Sewage Conduit extract (no need to extract)", "The Lab", ""),
        ]),
        "choices": ["Skipping the optional payments keeps Streets, Reserve or Lighthouse locked."],
        "reward": "Skier, Mechanic, Prapor and Peacekeeper; all 9 locations; Pathfinder achievement.",
    },
    {
        "id": "falling-skies", "name": "Falling Skies", "kind": "main",
        "start": "Find the downed plane in the nature reserve on Woods (east side).",
        "summary": "Investigate the crashed plane; ends with the armored case decision that shapes The Ticket.",
        "steps": _steps("fs", [
            ("Locate the crashed plane", "Woods", ""),
            ("Reach Loyalty Level 2 with Prapor (some editions skip this)", None, ""),
            ("Ask Prapor about the fallen plane", None, ""),
            ("Ask Therapist about the fallen plane", None, ""),
            ("Ask Skier about the fallen plane", None, ""),
            ("Ask Mechanic about the fallen plane", None, ""),
            ("Ask Jaeger about the fallen plane", None, ""),
            ("Pay Therapist $2,000 for the G-Wagon's location", None, "$2,000", "opt"),
            ("Get the flash drive from the G-Wagon by the Tunnel extract (driver-side step)", "Shoreline", ""),
            ("Give Prapor the flash drive, then wait about an hour", None, "Flash drive"),
            ("Take the flight recorder from the wreck (broken section near the back)", "Woods", ""),
            ("Stash the flight recorder in the island house on Fisherman's island", "Shoreline", "Flight recorder"),
            ("Give Prapor 2 Toolsets", None, "2 Toolsets (FiR or crafted)"),
            ("Give Prapor 3 Rechargeable batteries", None, "3 Rechargeable batteries"),
            ("Give Prapor 5 Printed circuit boards, then wait 3-5 hours", None, "5 Printed circuit boards"),
            ("Find the plane crew transcript (chairman's house, under the overturned bed's mattress)", "Shoreline", ""),
            ("Find Elektronik's flash drive (chairman's house, shelf by the bed)", "Shoreline", ""),
            ("Give Prapor the transcript and flash drive (say yes when he asks if you read it: paid twice)", None, "Transcript, Elektronik's flash drive"),
            ("Take the armored case from the plane (behind the cockpit)", "Woods", ""),
            ("Read Mr. Kerman's note on the pilot seat", "Woods", "", "opt"),
            ("Decide what to do with the armored case (no going back)", None, "Armored case"),
        ]),
        "choices": [
            "Give the case to Prapor: 1,500,000 ₽ (or 1,000,000 ₽ if you first pretend you didn't find it), Man of His Word. Adds the Lightkeeper arc to The Ticket.",
            "Keep the case: Prapor rep -0.7, Just Business. Skips the Lightkeeper arc; the Survivor ending costs more.",
        ],
        "reward": "Up to 1.5M ₽ depending on choices; unlocks The Ticket.",
    },
    {
        "id": "the-ticket", "name": "The Ticket", "kind": "main",
        "start": "After Falling Skies: build Intelligence Center 1 and contact Mr. Kerman from its laptop.",
        "summary": "The main story; leads to one of four endings, all finished at the Terminal.",
        "steps": _steps("ticket", [
            ("Build Intelligence Center level 1", None, ""),
            ("Contact Mr. Kerman from the Intelligence Center laptop", None, ""),
            ("Wait 2-6 hours for Mr. Kerman to reach out", None, ""),
            ("Talk to Prapor", None, ""),
            ("Report Prapor's words to Mr. Kerman (laptop)", None, ""),
            ("Find Prapor's people's camp (rocky west side)", "Lighthouse", "", "opt", "Gave Prapor the case"),
            ("Find the note from Prapor's men (ammo box lid or log by the guitar tent)", "Lighthouse", "", "opt", "Gave Prapor the case"),
            ("Tell Mr. Kerman what you found (unlocks Mechanic's To the Light - Trust but Verify)", None, "", "", "Gave Prapor the case"),
            ("Get into the lighthouse past Zryachiy (third floor locked door)", "Lighthouse", "Encoded DSP radio transmitter", "", "Gave Prapor the case"),
            ("Talk to Lightkeeper in person", "Lighthouse", "", "", "Gave Prapor the case"),
            ("Stay on good terms with Lightkeeper until he returns the case", "Lighthouse", "", "", "Gave Prapor the case"),
            ("Get 3 TerraGroup \"Blue Folders\" materials (flea is fine)", None, "3 Blue Folders", "", "Gave Prapor the case"),
            ("Hand the 3 Blue Folders to Lightkeeper in person", "Lighthouse", "3 Blue Folders", "", "Gave Prapor the case"),
            ("Fire a yellow flare at ULTRA's entrance", "Interchange", "Yellow signal flare", "", "Gave Prapor the case"),
            ("Get 15 kills on Interchange in one raid (dying redoes the flare too)", "Interchange", "", "", "Gave Prapor the case"),
            ("Receive the armored case from Lightkeeper (free special slot needed)", "Lighthouse", "", "", "Gave Prapor the case"),
            ("Get the experimental signal jammer (glass lab desks, R21 round table or R16 desk)", "The Lab", "TerraGroup Labs access keycard"),
            ("Talk to Mechanic about the jammer", None, "", "opt"),
            ("Ask Mechanic how the case opens", None, "", "opt"),
            ("Craft the armored case unlock (Workbench 1)", None, "Jammer recipe"),
            ("Unpack the case: Kruglov's RFID keycard and manual", None, ""),
            ("Read the RFID card manual (Handbook)", None, ""),
            ("Contact Mr. Kerman with the ticket information (point of no return)", None, ""),
            ("Make the final choice: go with Kerman, or refuse and pay Prapor", None, ""),
            ("Finale: Terminal intercom on Shoreline between 21:00 and 06:00 with your ending's access item", "Shoreline", "Ending access item"),
        ]),
        "choices": [
            "Survivor: refuse Kerman and pay Prapor 300M ₽ (gave him the case) or 500M ₽ (kept it).",
            "Savior: go with Kerman and deliver 8 of 9 evidence items (also needs Intelligence Center 3, Solar Power 1, 40 Physical Bitcoin, Fence rep 4.0 and more).",
            "Debtor: go with Kerman but stop after 2 evidence items.",
            "Fallen: go with Kerman, refuse to dig up dirt, leave with Prapor (dangerous cargo plus $1,000,000).",
        ],
        "reward": "One of four endings, finished at the Terminal; your gear goes back to how it was before the Terminal.",
    },
    {
        "id": "batya", "name": "Batya", "kind": "investigation",
        "start": "Find the Bogatyr patch (Customs, Woods, Reserve or Lighthouse).",
        "summary": "Learn what happened to the BEAR Bogatyr squad.",
        "steps": _steps("batya", [
            ("Find the Bogatyr patch and keep it (handed in later)", "Customs/Woods/Reserve/Lighthouse", ""),
            ("Ask Jaeger about the BEAR patch", None, "Bogatyr patch"),
            ("Find the Ryabina outpost north of the sawmill", "Woods", ""),
            ("Read Voevoda's hostage evacuation report (by the camp bottle)", "Woods", ""),
            ("Take Strelets' amulet from the sniper nest crate and keep it", "Woods", "", "opt"),
            ("Find the Carousel outpost inside ULTRA", "Interchange", ""),
            ("Take Taran's postcard by the beds and keep it", "Interchange", "", "opt"),
            ("Read Taran's personal file between the beds", "Interchange", ""),
            ("Take Voevoda's audio recorder from the radio table and keep it", "Interchange", ""),
            ("Find Voevoda's thoughts audio tape (radio table)", "Interchange", ""),
            ("Read Voevoda's personal file (upstairs desk)", "Interchange", ""),
            ("Read Strelets' personal file (upstairs armchair) and his note: code 27.893.2000", "Interchange", ""),
            ("Find the Gnezdo outpost east of ULTRA", "Interchange", ""),
            ("Gnezdo: audio report in the tent, Moreman's file, signal map under the rock", "Interchange", ""),
            ("Gnezdo: operations report by the guitar, first code note, BEAR note", "Interchange", ""),
            ("Find Moreman's grave near the ZB-016 extract", "Woods", ""),
            ("At the grave: second code note in a boot, phone and dogtag (keep the dogtag)", "Woods", ""),
            ("Combine the code notes: radio frequency 35.70", None, "Both code notes"),
            ("Craft and listen to Moreman's audio tapes #1 and #2 (Workbench 1, power on)", None, ""),
            ("Build Intelligence Center level 3", None, ""),
            ("Radio the squad: 35.70, code 27.893.2000", None, "Intelligence Center 3"),
            ("Get into the lighthouse past Zryachiy without harming his people", "Lighthouse", "Encoded DSP radio transmitter"),
            ("Give Lightkeeper the postcard, recorder, amulet, dogtag and patch", "Lighthouse", "Postcard, recorder, amulet, dogtag, patch"),
            ("Wait 6-12 hours for Voevoda to contact you", None, ""),
            ("Do Voevoda's combat and stat tasks", None, ""),
            ("Radio Voevoda again (35.70 / 27.893.2000)", None, "Intelligence Center 3"),
            ("Find the note about Prapor on a metal pole at the BEAR camp", "Lighthouse", ""),
            ("Question Prapor (trader menu)", None, ""),
            ("Find the notes linking the cultists to the General (west of the sawmill, or Customs dorm 314)", "Woods/Customs", "Dorm room 314 key (Customs route)"),
            ("Talk to Lightkeeper, wait 6 hours, then read the Agent network report on the red box", "Lighthouse", ""),
        ]),
        "choices": ["Harming Zryachiy, his followers or a Lightkeeper-friendly PMC breaks the transmitter decoding."],
        "reward": "This Is All (Not) Coincidence achievement; Voevoda's audio recorder.",
    },
    {
        "id": "accidental-witness", "name": "Accidental Witness", "kind": "investigation",
        "start": "Find the white car covered in scribbles in the Customs dorms courtyard.",
        "summary": "Kozlov, Anastasia and a debt collector's trail across Customs, Streets and Shoreline.",
        "steps": _steps("aw", [
            ("Find the scribbled-on car in the dorms courtyard", "Customs", ""),
            ("Find Kozlov's room (dorm 110, two-storey dorms, ground floor)", "Customs", ""),
            ("Read the note on Kozlov's door", "Customs", ""),
            ("Read the letter on Kozlov's nightstand", "Customs", "Dorm room 110 key"),
            ("Ask Skier about Anastasia", None, ""),
            ("Get into the accomplice's flat: Zmeisky 3, apartment 7 (backyard entrance)", "Streets of Tarkov", "Zmeisky 3 apartment key"),
            ("Read the four documents in the flat", "Streets of Tarkov", ""),
            ("Survive or Run Through Streets", "Streets of Tarkov", ""),
            ("Report to Skier", None, ""),
            ("Talk to Ragman about Anastasia's building", None, ""),
            ("Find Anastasia's flat: Chekannaya 13, apartment 7 (second floor)", "Streets of Tarkov", ""),
            ("Check the mailbox at her building's entrance", "Streets of Tarkov", ""),
            ("Find courier Pasha's ambush spot and the envelope", "Customs", ""),
            ("Tell Skier about Reshala's stash", None, ""),
            ("Get into Reshala's bunkhouse", "Customs", "Reshala's bunkhouse key (from Reshala)"),
            ("Read the three notes inside", "Customs", ""),
            ("Take Reshala's work notes and Pasha's belongings", "Customs", "", "opt"),
            ("Find Kozlov's hideout: house 3, east part of the west village", "Shoreline", ""),
            ("Listen to the audio tape in the flower bed by the entrance", "Shoreline", ""),
            ("Find the newspaper clipping with Anastasia's photo", "Shoreline", "", "opt"),
        ]),
        "choices": [],
        "reward": "Pay Your Debt achievement; rewards from Skier.",
    },
    {
        "id": "blue-fire", "name": "Blue Fire", "kind": "investigation",
        "start": "Read an EMERCOM leaflet (Woods Scav base container, Interchange tents or ULTRA medical unit, or the Labyrinth).",
        "summary": "Find out what caused the EMP blast and what Object 1156 is.",
        "steps": _steps("bf", [
            ("Pick up and read the EMERCOM leaflet", "Woods/Interchange", "EMERCOM leaflet"),
            ("Talk to Mechanic about the EMP blast", None, ""),
            ("Get the device fragment (LexOs 2nd floor food container, or Chekannaya 13 flower pot)", "Streets of Tarkov", "Car dealership closed section key or Mysterious room marked key"),
            ("Give Mechanic the device fragment", None, "Device fragment"),
            ("Plant the hacking device in the server room, first floor (done already if you did it in Boreas)", "The Lab", "Local network hacking device"),
            ("Talk to Mechanic", None, ""),
            ("Keep the fragment or hand it to Mechanic", None, "Device fragment"),
            ("Find a lead on Item 1156 (GZ office 4, Lighthouse bookshelf or Lab O22 desk)", "Ground Zero/Lighthouse/The Lab", "TerraGroup science office key (Ground Zero only)"),
            ("Investigate the Rus Post office", "Streets of Tarkov", "Audio recorder"),
            ("Find the first Rus Post tape (desk with screen behind the counter)", "Streets of Tarkov", ""),
            ("Find the second tape (top of the coffee machine by the storage room)", "Streets of Tarkov", ""),
            ("Find the third tape (back office desk)", "Streets of Tarkov", ""),
            ("Find the Rus Post car key (by the car's back right wheel)", "Streets of Tarkov", ""),
            ("Open the Rus Post car in front of the post office", "Streets of Tarkov", "Rus Post car key"),
            ("Read the Item 1156 blueprint in the back of the car", "Streets of Tarkov", ""),
        ]),
        "choices": ["Hand the fragment to Mechanic: 1,500,000 ₽. Keep it: Better Served achievement."],
        "reward": "Inferno achievement; 1.5M ₽ or Better Served.",
    },
    {
        "id": "boreas", "name": "Boreas", "kind": "investigation",
        "start": "Pick up a Paradigm Shipping poster in raid, or check the distress signal on the Intelligence Center 3 radio.",
        "summary": "Follow the distress signal to the frozen icebreaker Boreas.",
        "steps": _steps("boreas", [
            ("Read a Paradigm Shipping poster, or check the radio distress signal", None, ""),
            ("Ask traders about TerraGroup and Paradigm Shipping (or Mechanic about the signal)", None, ""),
            ("Repair the equipment under the cellular tower (Scav bunker), report to Mechanic", "Woods", "Toolset (used up)"),
            ("Get the Paradigm Shipping papers (freight yard warehouse, table by the lamp)", "Lighthouse", ""),
            ("Give Prapor AMG-10 hydraulic fluid for transport (extra cost depends on Falling Skies)", "Reserve", "AMG-10 hydraulic fluid (quest version)"),
            ("Find other transport through the BTR Driver's tasks (depends on your BTR history)", "Shoreline/Interchange/Customs", ""),
            ("Board the smuggler hovercraft at the Shoreline pier", "Shoreline", "400,000 ₽; green flare and €2,500 to leave"),
            ("Find surviving crew via the scientist's intercom (level 1, east)", "Icebreaker", ""),
            ("Reach the engine room (keycard in the level 1 medical room)", "Icebreaker", "Boreas engine room keycard (optional)"),
            ("Blow the chained engine room roof door", "Icebreaker", "SZ-1 explosive charge (Prapor LL1)"),
            ("Enter the superstructure; clear The Wedge in the crew quarters", "Icebreaker", ""),
            ("Get half the upper deck code from the scientist's intercom (door on level 5)", "Icebreaker", ""),
            ("Plant the hacking device in the Lab server room for the other half (done if you did it in Blue Fire)", "The Lab", "Local network hacking device"),
            ("Enter code 3-1-2-2-2-0 and thaw the bridge roof hatch", "Icebreaker", "BBQ-S43 gas torch (optional)"),
            ("Reach the captain on the bridge (level 9)", "Icebreaker", ""),
            ("Search Compartment C-1 for the three hard drives (level 7)", "Icebreaker", "Compartment C-1 keycard (body on level 9)"),
            ("Give Mechanic the decoding parts", None, "3 Ultralink modules, 4 Memento RAM, 2 IBX Gigachad processors"),
            ("Analyse the data, tell the scientist about the captain, arrange evacuation with the BTR Driver", None, ""),
            ("Help the smugglers against the Rogues and deliver the BTR Driver's requests", "Icebreaker", "5 respirators/gas masks, Kirasa-N armor, 2 class 5+ plates"),
        ]),
        "choices": [
            "AMG-10 step: nothing extra if you gave Prapor the case; 3 FiR Military power filters if you kept it; 30 Reserve kills and a flare if you never finished Falling Skies.",
            "BTR step depends on The Price of Independence / Choose Your Friends Wisely.",
        ],
        "reward": "Icebreaker access and its evidence trail; SZ-1 at Prapor; Compartment C-3 keycard.",
    },
    {
        "id": "the-labyrinth", "name": "The Labyrinth", "kind": "investigation",
        "start": "After Boreas: ask Jaeger about the underground facility.",
        "summary": "The TerraGroup facility under the Health Resort, reached by transit from Shoreline.",
        "steps": _steps("lab", [
            ("Ask Jaeger about the underground facility", None, ""),
            ("Ask Therapist how to get in (not the route)", None, "", "opt"),
            ("Agree to Jaeger's deal (BEAR squad information)", None, ""),
            ("Wait 12-24 hours, then talk to Jaeger again", None, ""),
            ("Collect the Labrys access keycards (2 by mail, more by barter)", None, ""),
            ("Find the Labyrinth transit in the Health Resort west wing basement", "Shoreline", "Knossos LLC facility key"),
            ("Enter the facility (one keycard per run, no insurance)", "The Labyrinth", "Labrys access keycard"),
            ("Get out of your spawn chamber (keys 01-04, valve, gas torch, levers)", "The Labyrinth", "BBQ-S43 gas torch for chambers 3 and 5"),
            ("Find Leshy's orders (food container in front of chamber 2)", "The Labyrinth", ""),
            ("Investigate the BEAR regroup spot at Item 1156 (prototype weapon area)", "The Labyrinth", ""),
            ("Find the squad leader and Leshy's diary (torture room)", "The Labyrinth", ""),
            ("Check the five lab staff bodies (the fourth needs the observation room key)", "The Labyrinth", "Observation room key"),
            ("Open the observation room and listen to the tape under the scientist's hand", "The Labyrinth", "Observation room key"),
            ("Give Jaeger the audio tape", None, "Audio tape"),
            ("Read the facility research report by the drain pipe next to the pier", "Shoreline", ""),
        ]),
        "choices": [],
        "reward": "500,000 ₽ and an AXMC .338 from Jaeger; Theseus achievement.",
    },
    {
        "id": "the-unheard", "name": "The Unheard", "kind": "investigation",
        "start": "Read the note rambling about the Purification (Streets, or Ground Zero 21+).",
        "summary": "Uncover who The Unheard are and what TerraGroup was shipping.",
        "steps": _steps("unheard", [
            ("Read the Purification note", "Streets of Tarkov/Ground Zero 21+", "TerraGroup science office key (Ground Zero only)"),
            ("Find the enterprise interaction document", "The Lab", ""),
            ("Find the cargo transport fax", "The Lab", ""),
            ("Find the special catalyst shipment info", "Factory", ""),
            ("Find Rzhevsky's service vehicle and take the hard drive", "Streets of Tarkov", ""),
            ("Craft the hard drive printout and read the transcript (Intelligence Center 1, power on)", None, "Rzhevsky's hard drive"),
            ("Find the TerraGroup storage room", "Factory", "TerraGroup storage room keycard"),
            ("Get the Blue Ice fuel catalyst report and the burnt document", "Factory", ""),
            ("Find A.P. on a whiteboard and A.P.'s two audio tapes", "The Lab", ""),
            ("Search A.P.'s room: east wing 305 (flash drive in the laptop, key in the right nightstand)", "Shoreline", ""),
            ("Craft the decrypted flash drive (Intelligence Center 1)", None, "Sliderkey flash drive"),
            ("Ask Mechanic for decryption help and pay him", None, "5,000,000 ₽, decrypted flash drive"),
            ("Wait for Elektronik (6-12 h, or 90 min if you've contacted Mr. Kerman)", None, ""),
            ("Craft the green A.P. apartment keycard (blue and red are decoys)", None, ""),
            ("Open the hidden room in Cardinal apartment 1 (second floor)", "Streets of Tarkov", "TerraGroup corporate apartment key, green keycard"),
            ("Read the TerraGroup order, the Blue Ice report copy, the protocol and the Warden documents", "Streets of Tarkov", ""),
        ]),
        "choices": [],
        "reward": "Trail of Breadcrumbs achievement.",
    },
    {
        "id": "they-are-already-here", "name": "They Are Already Here", "kind": "investigation",
        "start": "Read the note about the Eye of the World (Customs, Reserve, Woods or Shoreline).",
        "summary": "The cultists and the ARRS station network.",
        "steps": _steps("taah", [
            ("Read the note about the Eye of the World", "Customs/Reserve/Woods/Shoreline", ""),
            ("Equip an audio recorder", None, "Audio recorder"),
            ("Find a place linked to the Eye of the World", "Lighthouse", ""),
            ("Listen to cult victim tape #2 in the torture house", "Lighthouse", "Audio recorder"),
            ("Get the cult victim's apartment key", "Lighthouse", ""),
            ("Find the cult victim's apartment 5", "Streets of Tarkov", "Cult victim's apartment key"),
            ("Breach the office door, take the three items, the Book of the Arrival and the preparations note", "Streets of Tarkov", ""),
            ("Ask Mechanic about the Eye of the World", None, ""),
            ("Kill a Cultist priest", None, ""),
            ("Read more in the priest's note (marked rooms)", "Customs/Streets/Reserve", "Room key for the marked room"),
            ("Find the Eye of the World place: northern blue chalet, small southern bedroom (pass on the ATV by the garage)", "Lighthouse", ""),
            ("Find the Eye of the World place in the northern dilapidated village", "Woods", ""),
            ("Repair the Sordi tower (red shack near Road to Customs)", "Shoreline", "Toolset (used up)"),
            ("Ask Mechanic about Station 14-4 KORD", None, ""),
            ("Craft the restored Arshavin K. pass (Intelligence Center 1, power on)", None, "Damaged pass"),
            ("Get into NGO Cobalt's facility (power station basement) and restore power", "Interchange", "Restored pass"),
            ("Turn on server room cooling and install the flash drive", "Interchange", ""),
            ("Listen to the mysterious tape (safe by the entrance)", "Interchange", "Audio recorder"),
            ("Survive or Run Through and extract", "Interchange", ""),
            ("Read the ARRS mechanic's notes, press the reset button under the server table, THEN take the ARRS flash drive", "Interchange", ""),
            ("Survive or Run Through and extract again", "Interchange", ""),
            ("Give Mechanic the flash drive and read the ARRS specifications (Handbook)", None, "ARRS flash drive"),
        ]),
        "choices": ["Press the ARRS reset before taking the flash drive: doing it the other way round loses the specifications the Savior ending needs."],
        "reward": "When the Light Fades and Through Another's Eyes achievements.",
    },
]

BY_ID: Dict[str, dict] = {c["id"]: c for c in CHAPTERS}
STEP_IDS = {s["id"] for c in CHAPTERS for s in c["steps"]}


def chapter_status(chapter: dict, done: set) -> dict:
    """How far along a chapter is: counts and the next steps to do."""
    steps = chapter["steps"]
    # Steps on one route only (e.g. The Ticket's Lightkeeper arc) count once
    # you've started that route.
    routes = {s["branch"] for s in steps if s.get("branch") and s["id"] in done}
    required = [s for s in steps if not s["optional"] and (not s.get("branch") or s["branch"] in routes)]
    finished = [s for s in steps if s["id"] in done]
    left = [s for s in steps if s["id"] not in done and not s["optional"]]
    req_left = [s for s in required if s["id"] not in done]
    if not finished:
        state = "not started"
    elif not req_left:
        state = "done"
    else:
        state = "in progress"
    return {"state": state, "done": len(finished), "total": len(steps), "requiredLeft": len(req_left),
            "next": left[:3] if state != "done" else []}


def payload() -> dict:
    return {"chapters": CHAPTERS, "source": SOURCE, "sourceUrl": SOURCE_URL}


def find_step(step_id: str) -> Optional[dict]:
    for c in CHAPTERS:
        for s in c["steps"]:
            if s["id"] == step_id:
                return s
    return None
