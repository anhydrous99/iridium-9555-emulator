# Stored SIM messages through the factory handset

Four [Inbox journeys](../tests/test_factory_messages_inbox_e2e.py) pass on the
original HT25003 and HL25003 handsets. These are preloaded external SIM records,
not incoming RF messages. All three original processors and the real HTTP
controls execute normally; the card peer services only actual UART3 requests.

The finite fixture starts with one 176-byte unread SMS-DELIVER record and one
free record. Its GSM7 body is `adg`, sender is `+12345`, and service centre is
the deliberately different `+67890`. The timestamp is a declared input, not a
handset-clock assertion. The original storage scan exposes Inbox (1 unread),
then the list preview, full reader body and sender title. Opening/enumerating
Inbox changes card status `03` to `01` before explicit Read completes; the
cases do not incorrectly attribute that write solely to Read.

The two read/Reply/Forward journeys check every body glyph and trailing blank
area, the full sender title and original recipient node. Reply retains the
loaded `adg` body and exact sender `+12345` plus NUL, with kind zero, null name
and zero links. Editing it to `adga`, leaving Options and explicitly exiting
preserve the stored message. Forward retains `adg` and clears the original
recipient chain. Exiting leaves empty Drafts and healthy Home. Send and Call
are never selected; these local forms do not prove delivery.

The two deletion journeys first decline Delete and reread the complete stored
body and record. Confirming Yes requires the original Message Deleted and
No more messages dialogs, actual card commit, empty Inbox and Home. Original
CMGD changes status `01` to free `00` while retaining the old PDU bytes; it does
not erase the record to `FF`. The test checks all 176 bytes and the unchanged
second record. It also distinguishes the early completion dialog from the
later asynchronous card write.

Offline evidence verification checks 124 unique native LCD/state pairs,
88 original-font observations, six complete sender-node observations and
12 card observations. Actual UART3 write headers and complete committed bodies
are recorded. The existing finite MessageSIM and FactorySIMPeer sources remain
unchanged. No host-written guest cache, injected AT success or forced callback
stands in for the original read/write path.

The evidence is preserved with the factory storage/settings/GPS phase. Other
message lengths, character sets, timestamps, multi-message isolation and power
retention remain separate gaps. Network reception/notification, sending,
voice calls, delivery reports and email-gateway behavior remain unverified.
