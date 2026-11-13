

# ===========================================================================
# SECTION 5B - REPLIES, MATCHING AND RECONCILIATION
# ---------------------------------------------------------------------------
# A confirmation is sent, the party replies, and the reply has to be tied back
# to the right party and the confirmed figure read out of it.  Everything in
# this section is pure logic over plain dictionaries, so it works the same
# whether the reply arrived through the Gmail bridge, was pulled from a shared
# sheet, or was keyed in by hand.
#
# Reply record (one per message received):
#   {id, received_at, from_email, from_name, subject, body, thread_id,
#    in_reply_to, reference, attachments:[{name, text}], bounced}
#
# Match result added by match_reply():
#   {matched_document, match_method, match_confidence, client_run}
# ===========================================================================

REFERENCE_PREFIX = "BCG"
REFERENCE_RE = re.compile(r"\b" + REFERENCE_PREFIX + r"-([0-9A-HJ-NP-Z]{6})\b",
                          re.I)
# I, O, 0 and 1 are left out so a code read off a printed page is unambiguous
_REF_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def new_reference():
    """A short code printed in the subject and in the letter, e.g. BCG-7F3K2A."""
    import random
    return REFERENCE_PREFIX + "-" + "".join(
        random.choice(_REF_ALPHABET) for _ in range(6))


def find_reference(*texts):
    for text in texts:
        found = REFERENCE_RE.search(str(text or ""))
        if found:
            return (REFERENCE_PREFIX + "-" + found.group(1)).upper()
    return ""


def _norm_name(text):
    """Fold a party name for comparison: case, punctuation and the usual
    company suffixes all fall away."""
    value = str(text or "").lower()
    value = re.sub(r"[^a-z0-9 ]", " ", value)
    value = re.sub(r"\b(private|pvt|limited|ltd|llp|inc|co|company|and|&|the)\b",
                   " ", value)
    return re.sub(r"\s+", " ", value).strip()


def name_similarity(a, b):
    """0-100.  A token-set ratio, so word order and extra words do not matter.
    Written out rather than pulled from a library to keep the file standalone."""
    first, second = _norm_name(a), _norm_name(b)
    if not first or not second:
        return 0
    if first == second:
        return 100
    one, two = set(first.split()), set(second.split())
    shared = one & two
    if not shared:
        return 0
    # Jaccard over tokens, lifted when one name is wholly inside the other
    score = 100.0 * len(shared) / len(one | two)
    if one <= two or two <= one:
        score = max(score, 92.0)
    return int(round(score))


MATCH_THREAD = "thread"
MATCH_REFERENCE = "reference"
MATCH_SENDER = "sender address"
MATCH_NAME = "party name"
MATCH_NONE = "unmatched"

NAME_MATCH_THRESHOLD = 90


def match_reply(reply, documents):
    """Tie one reply to one sent confirmation.

    documents: the sent confirmations, each a dict carrying at least
    party_name, email, reference, thread_id and message_id.
    Returns (document or None, method, confidence 0-1).
    """
    haystacks = [reply.get("subject", ""), reply.get("body", "")]
    for attachment in reply.get("attachments") or []:
        haystacks.append(attachment.get("text", ""))

    # a) same Gmail thread as the message we sent - the strongest signal
    thread = str(reply.get("thread_id") or "")
    if thread:
        for document in documents:
            if document.get("thread_id") and document["thread_id"] == thread:
                return document, MATCH_THREAD, 1.0
    parent = str(reply.get("in_reply_to") or "")
    if parent:
        for document in documents:
            if document.get("message_id") and document["message_id"] == parent:
                return document, MATCH_THREAD, 1.0

    # b) our reference code quoted anywhere in the reply
    reference = reply.get("reference") or find_reference(*haystacks)
    if reference:
        for document in documents:
            if (document.get("reference") or "").upper() == reference.upper():
                return document, MATCH_REFERENCE, 0.98

    # c) the sender is the address the request went to
    sender = str(reply.get("from_email") or "").strip().lower()
    if sender:
        hits = [d for d in documents
                if str(d.get("email") or "").strip().lower() == sender]
        if len(hits) == 1:
            return hits[0], MATCH_SENDER, 0.9
        if len(hits) > 1:
            # same address used for several parties: fall through to the name
            scored = [(name_similarity(d.get("party_name"), text), d)
                      for d in hits
                      for text in haystacks + [reply.get("from_name", "")]]
            best_score, best = max(scored, key=lambda pair: pair[0])
            if best_score >= NAME_MATCH_THRESHOLD:
                return best, MATCH_SENDER, 0.85

    # d) the party's name appears in the reply or its attachment
    best, best_score = None, 0
    for document in documents:
        for text in haystacks + [reply.get("from_name", "")]:
            score = name_similarity(document.get("party_name"), text)
            # a long body can contain a name by chance, so require the name to
            # appear as a phrase, not merely share tokens
            if score > best_score and _norm_name(document.get("party_name")) \
                    and _norm_name(document.get("party_name")) in _norm_name(text):
                best, best_score = document, score
    if best is not None and best_score >= NAME_MATCH_THRESHOLD:
        return best, MATCH_NAME, round(0.6 + best_score / 500.0, 2)

    return None, MATCH_NONE, 0.0


# ------------------------------------------------------- reading the figure
# The slip the party completes reads:
#   "We hereby confirm that the amount payable by us to <client> as on
#    <date> is <CCY> ______________"
# and the letter above it STATES the client's own figure ("According to our
# records, the amount due from you ... is INR 35,00,000.00").  So a figure
# equal to the books proves nothing by itself: it may simply be our own
# letter coming back.  Every figure in the reply is therefore collected, and
# one that differs from the books always outranks an echo of the figure sent.
_CCY = r"(?:INR|USD|EUR|GBP|AED|SGD|AUD|CAD|JPY|CHF|Rs\.?|₹|\$|€|£)"
_FIGURE_RE = re.compile(
    r"(?P<ccy>" + _CCY + r")?[ \t]*"
    r"(?P<num>\(?-?\d(?:[\d,.]*\d)?\)?)"
    r"(?P<scale>[ \t]*(?:lakhs?|lacs?|crores?|millions?|thousands?)\b)?",
    re.I)
_SCALES = {"lakh": 1e5, "lac": 1e5, "crore": 1e7, "million": 1e6,
           "thousand": 1e3}
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep",
           "oct", "nov", "dec")
_KEYWORDS = ("balance", "amount", "outstanding", "payable", "receivable",
             "our books", "our records", "our ledger", "confirm", "advance",
             "due ")
_CONNECTOR_RE = re.compile(
    r"(?:\bis\b|\bof\b|\bbeing\b|\bwas\b|\bas\b|\bto be\b|\bshows?\b|"
    r"\bstands at\b|\bcomes to\b|[:=\-–])\s*$", re.I)
_SLIP_BEFORE_RE = re.compile(r"we\s+hereby\s+confirm[\s\S]{0,240}$", re.I)

# "as per our books" is deliberately absent: it introduces the party's own
# figure as often as it signals agreement
AGREE_WORDS = ["agree", "agreed", "in agreement", "confirmed", "confirm the "
               "balance", "tally", "tallies", "matches", "is correct"]
DISAGREE_WORDS = ["not in agreement", "do not agree", "does not agree",
                  "don't agree", "disagree", "difference", "differs",
                  "mismatch", "not tally", "does not tally", "discrepancy",
                  "not correct", "incorrect", "not matching", "does not match",
                  "do not match"]

BOUNCE_MARKERS = ["mailer-daemon", "postmaster", "delivery status "
                  "notification", "undeliverable", "address not found",
                  "delivery has failed", "returned to sender"]


def looks_like_bounce(reply):
    blob = " ".join([str(reply.get("from_email") or ""),
                     str(reply.get("from_name") or ""),
                     str(reply.get("subject") or ""),
                     str(reply.get("body") or "")]).lower()
    return any(marker in blob for marker in BOUNCE_MARKERS)


def strip_quoted(text):
    """The party's own words: the reply with the quoted original removed.

    A reply normally carries our covering e-mail underneath it, and that
    e-mail states the client's figure.  Read as the party's words, it would
    'confirm' the balance on its own."""
    text = str(text or "").replace("\r\n", "\n")
    cut = re.search(r"^[ \t>]*On\b[^\n]{0,240}(?:\n[^\n]{0,120})?\bwrote:[ \t]*$",
                    text, re.I | re.M)
    if cut:
        text = text[:cut.start()]
    kept = []
    for line in text.split("\n"):
        bare = line.strip()
        if bare.startswith(">"):
            continue
        if re.match(r"^-{2,}\s*(original|forwarded) message\s*-{2,}", bare,
                    re.I):
            break
        if re.match(r"^_{10,}$", bare):                    # Outlook divider
            break
        if kept and re.match(r"^from:\s.+", bare, re.I):   # Outlook header
            break
        kept.append(line)
    return "\n".join(kept).strip()


def _alone_on_line(blob, match):
    """True when a figure is all there is on its line (bar 'Rs', '/-',
    'only' and punctuation)."""
    line_start = blob.rfind("\n", 0, match.start()) + 1
    line_end = blob.find("\n", match.end())
    line = blob[line_start:line_end if line_end >= 0 else len(blob)]
    rest = line.replace(match.group(0), " ", 1)
    rest = re.sub(r"(?i)\b(rs|inr|only|rupees)\b|[\s./\-:=*₹]", "", rest)
    return rest == ""


_WELL_FORMED_RE = re.compile(
    r"^\(?-?(?:\d{1,2}(?:,\d{2})*,\d{3}|\d{1,3}(?:,\d{3})+|\d+)"
    r"(?:\.\d{1,2})?\)?$")


def _doubtful_reading(blob, start, end, raw, digits, scale):
    """True when OCR has plainly not read a figure whole.

    Handwriting comes back broken - '25, 00,0.00' for 25,00,000 - and the
    first fragment on its own would be recorded as 25.  A figure is trusted
    only if it is grouped like one and nothing figure-like hangs off it."""
    if not _WELL_FORMED_RE.match(raw):
        return True
    if re.match(r"^\s*[,.]\s*\d|^\s+\d", blob[end:end + 6]):
        return True                       # more digits follow after a gap
    if re.search(r"\d\s*[,.]\s+$|\d\s+[,.]\s*$", blob[max(0, start - 4):start]):
        return True                       # it is the tail of a broken figure
    if len(digits) < 4 and not scale:
        return True                       # '25' is not a balance
    return False


def find_figures(text, source, strict=False):
    """Every monetary figure in a piece of text, with how it was recognised.

    Returns [{amount, currency, confidence, source, kind, note}].  A bare
    number is only accepted where the wording around it says it is a balance;
    dates, pincodes and telephone numbers are left alone."""
    blob = re.sub(r"[ \t]+", " ", str(text or ""))
    found = []
    for match in _FIGURE_RE.finditer(blob):
        raw = match.group("num")
        start, end = match.start("num"), match.end("num")
        lead = blob[max(0, match.start() - 260):match.start()]
        after = blob[end:end + 14].lower()
        symbol = (match.group("ccy") or "").strip()
        scale = (match.group("scale") or "").strip().lower()
        digits = re.sub(r"\D", "", raw)

        # --- things that are not money
        if re.match(r"^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$", raw):   # 31.03.2026
            continue
        if not symbol and start > 1 and blob[start - 1] in "/-.@#" and \
                blob[start - 2].isalnum():                        # 31/03, BCG-7
            continue
        # "25,00,000/-" is how a rupee figure is commonly written, so a
        # trailing "/-" is money; any other slash is a date or a fraction
        if (after[:1] == "/" and not after.startswith("/-")) or \
                after[:1] in ("%", "@") or re.match(r"^-\d", after):
            continue
        if after.strip()[:3] in _MONTHS and len(digits) <= 2:     # 31 March
            continue
        if lead.rstrip().lower()[-3:] in _MONTHS or re.search(
                r"(january|february|march|april|june|july|august|september|"
                r"october|november|december)\s*,?\s*$", lead, re.I):
            if len(digits) <= 4 and "," not in raw:               # March 2026
                continue
        if not symbol and start and blob[start - 1].isalpha():    # ABC123
            continue
        if not symbol and re.match(r"^[a-z]", after):             # 10th road
            continue

        if not symbol and "," not in raw and re.match(r"^[6-9]\d{9}$", raw):
            continue                                              # a mobile

        grouped = bool(re.match(r"^\(?-?\d{1,3}(,\d{2,3})+(\.\d+)?\)?$", raw))
        marked = bool(symbol) or grouped or bool(scale)
        nearby = lead[-90:].lower()

        if _SLIP_BEFORE_RE.search(lead) and \
                re.search(r"\bis\b[\s:]*$", lead):
            kind, confidence = "slip", 0.95
        elif any(word in nearby for word in _KEYWORDS) and (
                marked or (5 <= len(digits) <= 12 and
                           _CONNECTOR_RE.search(lead[-40:]))):
            kind, confidence = "statement", 0.80
        elif symbol and (grouped or scale or len(digits) >= 4):
            kind, confidence = "figure", 0.60
        elif grouped and len(digits) >= 5 and _alone_on_line(blob, match):
            # a reply that is nothing but a figure: weak, but it is the
            # party's own, and a differing one must not be lost
            kind, confidence = "figure", 0.55
        else:
            continue

        value, currency_from_text, note = parse_amount(raw)
        if value is None:
            continue
        for word, factor in _SCALES.items():
            if scale.startswith(word):
                value *= factor
                break
        found.append({
            "amount": value,
            "currency": (currency_from_text or _CURRENCY_FROM_SYMBOL.get(
                symbol.upper().rstrip("."), "")),
            "confidence": confidence, "source": source, "kind": kind,
            "note": note or "",
            "doubtful": bool(strict and _doubtful_reading(
                blob, start, end, raw, digits, scale)),
            "seen": blob[start:end + 12].split("\n")[0].strip(),
        })
    return found


def extract_confirmation(reply, books=None, tolerance=1.0):
    """Read the confirmed figure and the party's stance out of a reply.

    books is the figure our letter carried.  When it is known, a figure in
    the reply that DIFFERS from it is the party's own and always wins; a
    figure that merely repeats it counts as agreement only if the party has
    not said otherwise.

    Returns {amount, currency, confidence, source, stance, confirmed_on,
             signed, note}.  A None amount means nothing could be relied on,
            which sends the reply to the exception queue rather than guessing.
    """
    result = {"amount": None, "currency": "", "confidence": 0.0,
              "source": "", "stance": "", "confirmed_on": "",
              "signed": False, "note": "", "method": ""}

    own_words = strip_quoted(reply.get("body", ""))
    candidates = []
    # the attachment is the signed slip, so it is read before the covering note
    for attachment in (reply.get("attachments") or []):
        by_ocr = "OCR" in str(attachment.get("method") or "")
        for figure in find_figures(attachment.get("text", ""),
                                   attachment.get("name", "attachment"),
                                   strict=by_ocr):
            figure["method"] = attachment.get("method", "")
            candidates.append(figure)
    candidates += find_figures(own_words, "email body")

    # A figure OCR could not read whole is never used.  Nor is one that is
    # out of all proportion to the balance asked about: that is a misread
    # digit or a telephone number, not a confirmation.
    for figure in candidates:
        if "OCR" in str(figure.get("method") or "") and books and \
                not figure["doubtful"]:
            ratio = abs(figure["amount"]) / abs(books)
            if ratio < 0.01 or ratio > 100:
                figure["doubtful"] = True
    doubtful = [c for c in candidates if c.get("doubtful")]
    candidates = [c for c in candidates if not c.get("doubtful")]

    lowered = own_words.lower()
    if any(word in lowered for word in DISAGREE_WORDS):
        result["stance"] = "not in agreement"
    elif any(word in lowered for word in AGREE_WORDS):
        result["stance"] = "agreed"

    chosen = None
    if candidates and books is not None:
        differing = [c for c in candidates
                     if abs(c["amount"] - books) > tolerance]
        if differing:
            # the party's own covering words outrank a figure on a document,
            # because the document may carry our pre-printed amount as well
            differing.sort(key=lambda c: (c["source"] == "email body",
                                          c["confidence"]), reverse=True)
            chosen = dict(differing[0])
            chosen["note"] = "Party states a figure different from the letter"
        elif result["stance"] == "not in agreement":
            result["note"] = ("Party says the balance is not in agreement but "
                              "gives no figure of its own")
        else:
            # Every figure found equals the books.  That is the party's own
            # confirmation only if it sits on the completed slip or in the
            # party's own words; the same figure in the body of the returned
            # letter is merely our own statement coming back.
            own = [c for c in candidates
                   if c["kind"] == "slip" or c["source"] == "email body"]
            if own:
                chosen = max(own, key=lambda c: c["confidence"])
            elif result["stance"] == "agreed":
                chosen = dict(max(candidates, key=lambda c: c["confidence"]))
                chosen["confidence"] = min(chosen["confidence"], 0.70)
                chosen["note"] = ("Party's covering words agree; the figure "
                                  "is the one stated in the letter")
            else:
                result["note"] = ("The letter came back, but the figure the "
                                  "party entered on the slip could not be "
                                  "read - open the reply")
    elif candidates:
        chosen = max(candidates, key=lambda c: c["confidence"])

    # The slip holds something OCR could not make out.  Unless the party has
    # stated its figure in its own words, that is for a person to read.
    unread_slip = [c for c in doubtful if c["kind"] == "slip"]
    if doubtful and (chosen is None or
                     (unread_slip and chosen["source"] != "email body")):
        seen = (unread_slip or doubtful)[0]
        chosen = None
        result["note"] = ("A figure is written on %s but could not be read "
                          "with certainty (OCR saw \"%s\") - open the "
                          "document" % (seen["source"], seen["seen"]))

    if chosen:
        result["method"] = chosen.get("method", "")
        result.update({"amount": chosen["amount"],
                       "currency": chosen["currency"],
                       "confidence": chosen["confidence"],
                       "source": chosen["source"],
                       "note": chosen.get("note", "")})
        if result["stance"] == "not in agreement":
            result["confidence"] = max(0.0, result["confidence"] - 0.05)

    blob = " ".join([str(reply.get("body") or "")] +
                    [str(a.get("text") or "")
                     for a in (reply.get("attachments") or [])]).lower()
    found_date = re.search(r"as on\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4}"
                           r"|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})", blob, re.I)
    if found_date:
        result["confirmed_on"] = iso_date(found_date.group(1))

    if re.search(r"\b(signed|signature|authorised signatory|"
                 r"authorized signatory|stamp|seal)\b", blob):
        result["signed"] = True
        if result["amount"] is not None:
            result["confidence"] = min(1.0, result["confidence"] + 0.02)

    return result


def is_own_request(reply, documents, own_addresses=()):
    """True when a 'reply' is really our own outgoing request.

    The request is copied to the engagement team, so it lands in the very
    mailbox the bridge reads - carrying a letter that states the client's own
    figure.  Counted as a reply it would 'agree' every balance by itself."""
    if reply.get("own_request"):
        return True
    message_id = str(reply.get("message_id") or "").strip()
    if message_id and any(str(d.get("message_id") or "").strip() == message_id
                          for d in documents):
        return True
    sender = str(reply.get("from_email") or "").strip().lower()
    own = {str(a or "").strip().lower() for a in own_addresses if a}
    if sender and sender in own:
        subject = str(reply.get("subject") or "").strip().lower()
        answered = bool(str(reply.get("in_reply_to") or "").strip()) or \
            bool(re.match(r"^(re|fw|fwd)\s*:", subject))
        if not answered:
            return True
    return False


_CURRENCY_FROM_SYMBOL = {"RS": "INR", "₹": "INR", "$": "USD",
                         "€": "EUR", "£": "GBP", "INR": "INR",
                         "USD": "USD", "EUR": "EUR", "GBP": "GBP",
                         "AED": "AED", "SGD": "SGD", "AUD": "AUD",
                         "CAD": "CAD", "JPY": "JPY", "CHF": "CHF"}


# -------------------------------------------------------- reconciliation
STATUS_AGREED = "Agreed"
STATUS_VARIANCE = "Mismatch"
STATUS_PENDING = "Pending"
STATUS_RETURNED = "Returned"
STATUS_REVIEW = "Needs review"
STATUS_NOT_SENT = "Not sent"

STATUS_ORDER = [STATUS_VARIANCE, STATUS_REVIEW, STATUS_RETURNED,
                STATUS_PENDING, STATUS_AGREED, STATUS_NOT_SENT]

DEFAULT_TOLERANCE = 1.0          # INR; a rounding difference is not a variance
DEFAULT_REMINDERS = (15, 30, 45)  # days after sending


def days_between(earlier, later=None):
    start = to_date(earlier)
    if not start:
        return None
    end = to_date(later) if later else date.today()
    return (end - start).days


def reminder_stage(age_days, stages=DEFAULT_REMINDERS):
    """Which reminder is due for a confirmation this old (0 = none yet)."""
    if age_days is None:
        return 0
    due = 0
    for index, threshold in enumerate(sorted(stages), start=1):
        if age_days >= threshold:
            due = index
    return due


def reconcile(document, reply=None, tolerance=DEFAULT_TOLERANCE,
              reminders=DEFAULT_REMINDERS, today=None):
    """Compare one sent confirmation with the reply received for it.

    The sign convention is already handled by the letter wording: whatever the
    category, the party confirms the same balance the client has recorded, so
    the two figures are compared directly and never reversed.
    """
    books = document.get("amount")
    currency = document.get("currency") or ""
    sent_on = document.get("sent_at") or document.get("generated_at")
    age = days_between(sent_on, today)

    row = {
        "document_id": document.get("id") or document.get("filename"),
        "party_name": document.get("party_name", ""),
        "category": document.get("category", ""),
        "email": document.get("email", ""),
        "reference": document.get("reference", ""),
        "filename": document.get("filename", ""),
        "currency": currency,
        "books_amount": books,
        "confirmed_amount": None,
        "variance": None,
        "variance_pct": None,
        "status": STATUS_PENDING,
        "delivery": str(document.get("email_status") or "not sent"),
        "sent_at": sent_on or "",
        "received_at": "",
        "age_days": age,
        "reminder_stage": 0,
        "match_method": "",
        "match_confidence": 0.0,
        "extract_confidence": 0.0,
        "extract_source": "",
        "stance": "",
        "signed": False,
        "message_link": "",
        "note": "",
    }

    delivery = str(document.get("email_status") or "").lower()
    if delivery in ("", "not sent"):
        row["status"] = STATUS_NOT_SENT
        row["note"] = "Letter produced but not e-mailed"
        return row
    if delivery == "failed":
        row["status"] = STATUS_RETURNED
        row["note"] = "Delivery failed"
        return row

    if reply is None:
        row["reminder_stage"] = reminder_stage(age, reminders)
        return row

    row["received_at"] = reply.get("received_at", "")
    row["match_method"] = reply.get("match_method", "")
    row["match_confidence"] = reply.get("match_confidence", 0.0)
    row["message_link"] = reply.get("message_link", "")

    if reply.get("bounced") or looks_like_bounce(reply):
        row["status"] = STATUS_RETURNED
        row["note"] = "Mail returned undelivered"
        return row

    # always read against the figure our letter carried: the letter coming
    # back must not be mistaken for the party's own confirmation
    extraction = extract_confirmation(reply, books, tolerance)
    row["extract_confidence"] = extraction.get("confidence", 0.0)
    row["extract_source"] = extraction.get("source", "")
    row["stance"] = extraction.get("stance", "")
    row["signed"] = extraction.get("signed", False)
    if extraction.get("currency"):
        row["currency"] = extraction["currency"]

    confirmed = extraction.get("amount")
    if confirmed is None:
        row["status"] = STATUS_REVIEW
        row["note"] = extraction.get("note") or \
            "Reply received but no amount could be read"
        if reply.get("files_error"):
            row["note"] += " - attachment not read: " + \
                str(reply["files_error"])[:160]
        elif reply_has_unread_files(reply):
            row["note"] += " - it has a PDF or scan that has not been read " \
                           "yet (Read attached PDFs)"
        return row

    row["confirmed_amount"] = confirmed
    if books is None:
        row["status"] = STATUS_REVIEW
        row["note"] = "No balance on record to compare with"
        return row

    variance = confirmed - books
    row["variance"] = variance
    row["variance_pct"] = (abs(variance) / abs(books) * 100.0) if books else None
    if abs(variance) <= tolerance:
        row["status"] = STATUS_AGREED
        row["note"] = "Agrees with the books"
    else:
        row["status"] = STATUS_VARIANCE
        row["note"] = "Party confirms %s the books by %s" % (
            "less than" if variance < 0 else "more than",
            fmt_amount(abs(variance), row["currency"]) or abs(variance))
    if "OCR" in str(extraction.get("method") or ""):
        # how the figure was obtained travels with it into every report
        row["note"] += " (read by OCR from %s - check against the document)" \
            % (row["extract_source"] or "the attachment")
    return row


def build_reconciliation(documents, replies, tolerance=DEFAULT_TOLERANCE,
                         reminders=DEFAULT_REMINDERS, today=None,
                         own_addresses=(), ignored=None):
    """Match every reply, then reconcile every sent confirmation.

    Returns (rows, exceptions).  Exceptions are replies that could not be tied
    to a party, or whose figure could not be read with confidence - they are
    never folded into the numbers silently.
    """
    by_document, exceptions = {}, []

    for reply in replies:
        if is_own_request(reply, documents, own_addresses):
            if ignored is not None:          # our own letter, not an answer
                ignored.append(reply)
            continue
        document, method, confidence = match_reply(reply, documents)
        enriched = dict(reply)
        enriched["match_method"] = method
        enriched["match_confidence"] = confidence
        enriched["extraction"] = extract_confirmation(
            reply, document.get("amount") if document else None, tolerance)
        if document is None:
            exceptions.append({
                "reason": "Sender could not be matched to a party",
                "from_email": reply.get("from_email", ""),
                "from_name": reply.get("from_name", ""),
                "subject": reply.get("subject", ""),
                "received_at": reply.get("received_at", ""),
                "amount": enriched["extraction"].get("amount"),
                "currency": enriched["extraction"].get("currency", ""),
                "confidence": enriched["extraction"].get("confidence", 0.0),
                "reply_id": reply.get("id", ""),
                "message_link": reply.get("message_link", ""),
            })
            continue
        key = document.get("id") or document.get("filename")
        # if two replies match the same party, the later one wins
        previous = by_document.get(key)
        if previous is None or str(enriched.get("received_at", "")) >= \
                str(previous.get("received_at", "")):
            by_document[key] = enriched

    rows = []
    for document in documents:
        key = document.get("id") or document.get("filename")
        row = reconcile(document, by_document.get(key), tolerance, reminders,
                        today)
        rows.append(row)
        if row["status"] == STATUS_REVIEW and by_document.get(key):
            reply = by_document[key]
            exceptions.append({
                "reason": row["note"] or "Needs review",
                "from_email": reply.get("from_email", ""),
                "from_name": row["party_name"],
                "subject": reply.get("subject", ""),
                "received_at": reply.get("received_at", ""),
                "amount": reply.get("extraction", {}).get("amount"),
                "currency": row["currency"],
                "confidence": reply.get("extraction", {}).get("confidence", 0.0),
                "reply_id": reply.get("id", ""),
                "message_link": reply.get("message_link", ""),
            })

    rows.sort(key=lambda r: (STATUS_ORDER.index(r["status"])
                             if r["status"] in STATUS_ORDER else 99,
                             r["party_name"].lower()))
    return rows, exceptions


def summarise(rows):
    """Headline figures for the dashboard and the variance report."""
    def total(selector):
        return sum(abs(r["books_amount"]) for r in rows
                   if selector(r) and r["books_amount"] is not None)

    received = [r for r in rows if r["status"] in
                (STATUS_AGREED, STATUS_VARIANCE)]
    requested_value = total(lambda r: r["status"] != STATUS_NOT_SENT)
    confirmed_value = sum(abs(r["books_amount"]) for r in received
                          if r["books_amount"] is not None)
    return {
        "sent": len([r for r in rows if r["status"] != STATUS_NOT_SENT]),
        "received": len(received),
        "agreed": len([r for r in rows if r["status"] == STATUS_AGREED]),
        "variance": len([r for r in rows if r["status"] == STATUS_VARIANCE]),
        "pending": len([r for r in rows if r["status"] == STATUS_PENDING]),
        "returned": len([r for r in rows if r["status"] == STATUS_RETURNED]),
        "review": len([r for r in rows if r["status"] == STATUS_REVIEW]),
        "not_sent": len([r for r in rows if r["status"] == STATUS_NOT_SENT]),
        "requested_value": requested_value,
        "confirmed_value": confirmed_value,
        "coverage_pct": (confirmed_value / requested_value * 100.0)
                        if requested_value else 0.0,
        "returned": len([r for r in rows if r["status"] == STATUS_RETURNED]),
        "review": len([r for r in rows if r["status"] == STATUS_REVIEW]),
        "net_variance": sum(r["variance"] for r in rows
                            if r["variance"] is not None),
        "gross_variance": sum(abs(r["variance"]) for r in rows
                              if r["variance"] is not None),
    }


def summarise_by_category(rows):
    """The same figures split by balance category - the working-paper view."""
    out = []
    for category in CATEGORIES:
        subset = [r for r in rows if r["category"] == category]
        if not subset:
            continue
        stats = summarise(subset)
        stats["category"] = category
        stats["parties"] = len(subset)
        out.append(stats)
    return out
