
    # =====================================================================
    # PAGE 08 - CONFIRMATIONS RECEIVED
    # ---------------------------------------------------------------------
    # The replies that came back, reconciled against what was sent, with the
    # six reports an auditor puts in the working papers.  Replies reach this
    # page from the saved records; the Gmail bridge writes into the same
    # place, so nothing here has to change when it is connected.
    # =====================================================================
    def _page_recon(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 26)
        layout.setSpacing(16)

        frame, body, header = card("Position", "")
        self.recon_scope = QLabel("")
        self.recon_scope.setObjectName("HintDark")
        header.addWidget(self.recon_scope)
        refresh = button("Recalculate")
        refresh.clicked.connect(self.refresh_recon)
        sync = button("Sync Gmail bridge", "primary")
        sync.setToolTip(
            "Read the replies the Apps Script has been collecting on Google's "
            "servers since the last sync")
        sync.clicked.connect(lambda: self.sync_bridge())
        import_replies = button("Import replies (JSON)…", "brass")
        import_replies.setToolTip(
            "Load replies from a file you have prepared or downloaded "
            "yourself")
        import_replies.clicked.connect(self.import_replies)
        header.addWidget(refresh)
        header.addWidget(sync)
        header.addWidget(import_replies)

        self.bridge_note = QLabel("")
        self.bridge_note.setObjectName("HintDark")
        body.addWidget(self.bridge_note)

        # the reply's own document: fetched, opened and read on this computer
        reader_row = QHBoxLayout()
        reader_row.setSpacing(8)
        self.btn_read_docs = button("Read attached PDFs (OCR)", "primary")
        self.btn_read_docs.setToolTip(
            "Download each reply's PDF or scan from the bridge and read the "
            "confirmed amount from it on this computer")
        self.btn_read_docs.clicked.connect(
            lambda: self.read_reply_documents(retry=True))
        self.btn_add_pdf = button("Add a reply from a PDF or scan…")
        self.btn_add_pdf.setToolTip(
            "For a confirmation received by post, by hand or on another "
            "mailbox: the file is read and matched to its party")
        self.btn_add_pdf.clicked.connect(lambda: self.add_reply_from_file())
        self.reader_note = QLabel("")
        self.reader_note.setObjectName("HintDark")
        self.reader_note.setWordWrap(True)
        reader_row.addWidget(self.btn_read_docs)
        reader_row.addWidget(self.btn_add_pdf)
        reader_row.addWidget(self.reader_note, 1)
        body.addLayout(reader_row)
        self.recon_stats = QHBoxLayout()
        self.recon_stats.setSpacing(10)
        body.addLayout(self.recon_stats)
        layout.addWidget(frame)

        frame2, body2, header2 = card("Reports", "", light=True)
        self.report_note = QLabel("")
        self.report_note.setObjectName("HintLight")
        header2.addWidget(self.report_note)
        self.btn_assign = button("Assign reply…")
        self.btn_assign.setToolTip(
            "Decide which party a reply in the exception queue belongs to, "
            "or set it aside as not being a confirmation")
        self.btn_assign.clicked.connect(self.assign_selected_reply)
        header2.addWidget(self.btn_assign)
        excel = button("Export all to Excel", "primary")
        excel.clicked.connect(self.export_reports_excel)
        pdf = button("Export all to PDF", "blue")
        pdf.clicked.connect(self.export_reports_pdf)
        header2.addWidget(excel)
        header2.addWidget(pdf)

        chooser = QHBoxLayout()
        chooser.setSpacing(8)
        chooser.addWidget(field_label("Report", light=True))
        self.report_combo = QComboBox()
        for key, title, _subtitle in REPORT_TITLES:
            self.report_combo.addItem(title, key)
        self.report_combo.setMinimumWidth(300)
        self.report_combo.currentIndexChanged.connect(self.render_report)
        chooser.addWidget(self.report_combo)
        self.report_subtitle = QLabel("")
        self.report_subtitle.setObjectName("HintLight")
        chooser.addWidget(self.report_subtitle)
        chooser.addStretch(1)
        body2.addLayout(chooser)

        self.report_table = table([""])
        self.report_table.setMinimumHeight(360)
        body2.addWidget(self.report_table)
        self.report_totals = QLabel("")
        self.report_totals.setObjectName("HintLight")
        self.report_totals.setWordWrap(True)
        body2.addWidget(self.report_totals)
        layout.addWidget(frame2, 1)
        return page

    # ----------------------------------------------------------- the data
    def sent_documents(self):
        """Every confirmation issued for the active client and year, flattened
        out of the saved runs so repeat runs do not double-count a party."""
        client = self.active_client()
        year = self.active_fy()
        if not client or not year:
            return []
        documents, seen = [], set()
        for run in self.db["runs"]:
            if run.get("client_id") != client["id"] or \
                    run.get("fy_id") != year["id"]:
                continue
            for document in run.get("documents", []):
                key = (document.get("party_name", ""),
                       document.get("category", ""))
                if key in seen:          # a later run supersedes an earlier one
                    continue
                seen.add(key)
                entry = dict(document)
                entry.setdefault("id", document.get("filename"))
                entry.setdefault("sent_at", document.get("email_at")
                                 or document.get("generated_at"))
                documents.append(entry)
        return documents

    def stored_replies(self):
        client = self.active_client()
        year = self.active_fy()
        if not client or not year:
            return []
        return [r for r in self.db.get("replies", [])
                if r.get("client_id") in (None, client["id"])
                and r.get("fy_id") in (None, year["id"])]

    def refresh_recon(self):
        documents = self.sent_documents()
        replies = self.stored_replies()
        settings = self.db["settings"]
        mail = settings.get("mail") or {}
        self.recon_ignored = []
        self.recon_set_aside = []
        self.recon_rows, self.recon_exceptions = build_reconciliation(
            documents, replies,
            tolerance=float(settings.get("variance_tolerance",
                                         DEFAULT_TOLERANCE)),
            reminders=tuple(settings.get("reminder_days", DEFAULT_REMINDERS)),
            # the request is copied to the team, so it comes back through the
            # bridge: our own letter must never be counted as a reply
            own_addresses=(mail.get("username"), mail.get("sender")),
            ignored=self.recon_ignored, set_aside=self.recon_set_aside)
        self.recon_summary = summarise(self.recon_rows)

        client = self.active_client()
        year = self.active_fy()
        self.recon_scope.setText(
            "%s · %s · %d confirmations issued, %d replies on record%s"
            % (client["name"] if client else "no client",
               year["year"] if year else "no year",
               len(documents), len(replies) - len(self.recon_ignored),
               ((" · %d cop%s of your own request ignored"
                 % (len(self.recon_ignored),
                    "y" if len(self.recon_ignored) == 1 else "ies"))
                if self.recon_ignored else "") +
               ((" · %d set aside" % len(self.recon_set_aside))
                if self.recon_set_aside else ""))
            if client else "Select a client to see its position")

        summary = self.recon_summary
        self._clear(self.recon_stats)
        for key, value, meta, accent in (
                ("Sent", summary["sent"], "Confirmations issued", T["accent"]),
                ("Received", summary["received"], "Replies matched", T["info"]),
                ("Agreed", summary["agreed"], "Within tolerance", T["ok"]),
                ("Mismatch", summary["variance"],
                 "Differs from books", T["err"]),
                ("Review", len(self.recon_exceptions),
                 "Replies to decide", T["warn"]),
                ("Pending", summary["pending"], "No reply yet", T["text_mute"]),
                ("Returned", summary["returned"], "Undelivered", T["err"]),
                ("Coverage", "%.1f%%" % summary["coverage_pct"],
                 "By value of balances", T["accent_hi"])):
            self.recon_stats.addWidget(stat_card(key, value, meta, accent))
        self.recon_stats.addStretch(1)
        self.refresh_bridge_note()
        self.refresh_reader_note()
        self.render_report()
        self.refresh_chips()

    def current_reports(self):
        if not hasattr(self, "recon_rows"):
            self.recon_rows, self.recon_exceptions = [], []
        return build_all_reports(
            self.recon_rows, self.recon_exceptions,
            {"reminders": tuple(self.db["settings"].get("reminder_days",
                                                        DEFAULT_REMINDERS))})

    def render_report(self):
        key = self.report_combo.currentData()
        report = build_report(key, getattr(self, "recon_rows", []),
                              getattr(self, "recon_exceptions", []),
                              {"reminders": tuple(
                                  self.db["settings"].get("reminder_days",
                                                          DEFAULT_REMINDERS))})
        self.report_subtitle.setText(report["subtitle"])
        if hasattr(self, "btn_assign"):
            self.btn_assign.setVisible(key == REPORT_EXCEPTIONS)
        headings = [h for h, _k, _t in report["columns"]]
        self.report_table.clear()
        self.report_table.setColumnCount(len(headings))
        self.report_table.setHorizontalHeaderLabels(headings)
        self.report_table.setRowCount(len(report["rows"]))

        tone = {STATUS_AGREED: T["ok"], STATUS_VARIANCE: T["err"],
                STATUS_REVIEW: T["err"], STATUS_RETURNED: T["err"],
                STATUS_PENDING: T["text_mute"], STATUS_NOT_SENT: T["text_mute"]}
        for row_index, row in enumerate(report["rows"]):
            currency = row.get("currency") or "INR"
            for column_index, (_heading, field, kind) in enumerate(
                    report["columns"]):
                value = row.get(field)
                text = format_cell(value, kind, currency)
                item = cell(text,
                            align_right=kind in ("money", "number", "pct",
                                                 "pct_unit"),
                            color=tone.get(value) if kind == "status" else None,
                            bold=kind == "status")
                self.report_table.setItem(row_index, column_index, item)
        self.report_table.resizeColumnsToContents()
        # fill the width rather than leaving a bare strip beside the last column
        self.report_table.horizontalHeader().setStretchLastSection(True)

        if report["totals"]:
            parts = []
            for heading, field, kind in report["columns"]:
                if field in report["totals"]:
                    parts.append("%s: %s" % (heading,
                                             format_cell(report["totals"][field],
                                                         kind, "INR")))
            self.report_totals.setText("Total — " + " · ".join(parts))
        else:
            self.report_totals.setText("")
        self.report_note.setText("%d row%s" % (len(report["rows"]),
                                               "" if len(report["rows"]) == 1
                                               else "s"))

    # ------------------------------------------- deciding a reply by hand
    def assign_reply(self, reply_id, target):
        """Record the auditor's decision on one reply.

        target is a confirmation's id, SET_ASIDE (not a confirmation for any
        party), or "" to hand the reply back to automatic matching.  The
        decision and when it was made are kept on the reply itself."""
        for reply in self.db.get("replies", []):
            if str(reply.get("id")) != str(reply_id):
                continue
            if target:
                reply["assigned_to"] = target
                reply["assigned_at"] = datetime.now().isoformat(
                    timespec="seconds")
            else:
                reply.pop("assigned_to", None)
                reply.pop("assigned_at", None)
            self.persist()
            self.refresh_recon()
            return True
        return False

    def assign_selected_reply(self):
        if self.report_combo.currentData() != REPORT_EXCEPTIONS:
            self.toast("Open the Exception queue and select a reply first.",
                       "warn")
            return
        index = self.report_table.currentRow()
        queue = getattr(self, "recon_exceptions", [])
        if index < 0 or index >= len(queue):
            self.toast("Select a reply in the Exception queue first.", "warn")
            return
        entry = queue[index]
        if not entry.get("reply_id"):
            self.toast("That row has no reply to assign.", "warn")
            return
        target = self.choose_party_dialog(entry)
        if target is None:
            return
        self.assign_reply(entry["reply_id"], target)
        if target == SET_ASIDE:
            self.toast("Reply set aside: it is kept on record but not "
                       "counted.", "ok")
        elif target:
            party = next((d.get("party_name") for d in self.sent_documents()
                          if document_key(d) == target), "the party")
            self.toast("Reply recorded against %s." % party, "ok")
        else:
            self.toast("Reply handed back to automatic matching.", "ok")

    def choose_party_dialog(self, entry):
        """Ask which confirmation a reply answers.  Returns a document id,
        SET_ASIDE, "" for automatic matching, or None if cancelled."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Assign reply")
        layout = QVBoxLayout(dialog)
        facts = QLabel(
            "<b>From:</b> %s<br><b>Received:</b> %s<br><b>Subject:</b> %s"
            "<br><b>Amount read:</b> %s<br><b>Why it is here:</b> %s" % (
                xml_escape(entry.get("from_email") or "unknown"),
                xml_escape(fmt_date_long(str(entry.get("received_at")
                                             or "")[:10]) or
                           str(entry.get("received_at") or "")),
                xml_escape(entry.get("subject") or ""),
                xml_escape(fmt_amount(entry.get("amount"),
                                      entry.get("currency") or "INR")
                           or "none"),
                xml_escape(entry.get("reason") or "")))
        facts.setWordWrap(True)
        layout.addWidget(facts)
        layout.addWidget(QLabel("Record this reply against:"))
        combo = QComboBox()
        for document in sorted(self.sent_documents(),
                               key=lambda d: (d.get("party_name", "").lower(),
                                              d.get("category", ""))):
            combo.addItem("%s — %s — %s" % (
                document.get("party_name", ""), document.get("category", ""),
                fmt_amount(document.get("amount"),
                           document.get("currency") or "INR")),
                document_key(document))
        combo.addItem("Set aside — not a confirmation for any party",
                      SET_ASIDE)
        combo.addItem("Return it to automatic matching", "")
        layout.addWidget(combo)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return combo.currentData()

    # --------------------------------------------------------- the exports
    def report_heading(self):
        client = self.active_client()
        year = self.active_fy()
        summary = getattr(self, "recon_summary", None) or summarise([])
        facts = [("Client", client["name"] if client else "—"),
                 ("Financial year", year["year"] if year else "—"),
                 ("Confirmations as at",
                  fmt_date_long(fy_as_at(year)) if year else "—"),
                 ("Type of audit", fy_audit_type(year) if year else "—"),
                 ("Audit firm", self.db["settings"].get("firm_name", "")),
                 ("Prepared on", fmt_date_long(date.today())),
                 ("Coverage by value", "%.2f%%" % summary["coverage_pct"])]
        return {"title": "Balance confirmation — reconciliation reports",
                "author": self.db["settings"].get("firm_name", ""),
                "facts": facts}

    def _export_path(self, extension, label):
        client = self.active_client()
        year = self.active_fy()
        base = sanitize_filename("%s - Balance confirmation %s - %s"
                                 % (client["name"] if client else "Client",
                                    label, year["year"] if year else ""))
        start = os.path.join(self.db["settings"].get("output_folder")
                             or os.path.expanduser("~"), base + extension)
        path, _ = QFileDialog.getSaveFileName(
            self, "Save the reports", start,
            ("Excel workbook (*.xlsx)" if extension == ".xlsx"
             else "PDF document (*.pdf)"))
        return path

    def export_reports_excel(self):
        if not getattr(self, "recon_rows", None):
            self.toast("Nothing to report yet — send some confirmations "
                       "first.", "warn")
            return
        path = self._export_path(".xlsx", "reports")
        if not path:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            write_reports_xlsx(path, self.current_reports(),
                               self.report_heading())
            QApplication.restoreOverrideCursor()
            self.toast("Workbook written to %s" % path, "ok")
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            self.toast("The workbook could not be written: %s" % exc, "err")

    def export_reports_pdf(self):
        if not getattr(self, "recon_rows", None):
            self.toast("Nothing to report yet — send some confirmations "
                       "first.", "warn")
            return
        path = self._export_path(".pdf", "reports")
        if not path:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            write_reports_pdf(path, self.current_reports(),
                              self.report_heading())
            QApplication.restoreOverrideCursor()
            self.toast("PDF written to %s" % path, "ok")
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            self.toast("The PDF could not be written: %s" % exc, "err")

    def import_replies(self):
        """Load replies from a JSON file: a list of reply records, or the
        object the Gmail bridge writes ({"replies": [...]})."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import replies", os.path.expanduser("~"),
            "JSON files (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception as exc:
            self.toast("That file is not valid JSON: %s" % exc, "err")
            return
        incoming = payload.get("replies") if isinstance(payload, dict) \
            else payload
        if not isinstance(incoming, list):
            self.toast("That file does not hold a list of replies.", "err")
            return
        added, seen = self.merge_replies(incoming)
        self.toast("%d new repl%s imported (%d already on record)."
                   % (added, "y" if added == 1 else "ies", seen - added), "ok")

    def merge_replies(self, incoming):
        """Add replies that are not already on record.  Returns the number
        added and the number offered, so both the file import and the bridge
        sync can report the same way."""
        client = self.active_client()
        year = self.active_fy()
        store = self.db.setdefault("replies", [])
        known = {r.get("id") for r in store}
        added = offered = 0
        for reply in incoming:
            if not isinstance(reply, dict):
                continue
            offered += 1
            reply = dict(reply)
            reply.setdefault("id", new_id())
            if reply["id"] in known:            # never count a reply twice
                # ...but learn what is attached, if the bridge now says so
                if reply.get("files"):
                    for held in store:
                        if held.get("id") == reply["id"] and \
                                not held.get("files"):
                            held["files"] = list(reply["files"])
                continue
            reply.setdefault("client_id", client["id"] if client else None)
            reply.setdefault("fy_id", year["id"] if year else None)
            store.append(reply)
            known.add(reply["id"])
            added += 1
        self.persist()
        self.refresh_recon()
        return added, offered

    # ------------------------------------------------- the always-on bridge
    def sync_bridge(self, quiet=False):
        """Read the feed published by the Gmail Apps Script.  The script
        collects replies on Google's servers while this computer is off; this
        is the one call that brings them across."""
        url = (self.db["settings"].get("bridge_feed_url") or "").strip()
        if not url:
            if not quiet:
                self.toast("No bridge address saved.  Settings > Gmail bridge.",
                           "warn")
            return
        if not url.lower().startswith("https://"):
            if not quiet:
                self.toast("The bridge address must begin with https://",
                           "err")
            return
        if getattr(self, "bridge_thread", None):      # one read at a time
            if not quiet:
                self.toast("The bridge is already being read.", "warn")
            return

        if not quiet:
            self.toast("Reading the bridge…", "info")
        self.bridge_thread = QThread(self)
        self.bridge_worker = BridgeWorker(url)
        self.bridge_worker.moveToThread(self.bridge_thread)
        self.bridge_thread.started.connect(self.bridge_worker.run)
        self.bridge_worker.finished.connect(
            lambda replies, error: self.on_bridge_finished(replies, error,
                                                           quiet))
        self.bridge_thread.start()

    def on_bridge_finished(self, replies, error, quiet):
        thread = getattr(self, "bridge_thread", None)
        if thread:
            thread.quit()
            thread.wait(3000)
        self.bridge_thread = None
        self.bridge_worker = None

        if error:
            if not quiet:
                self.toast("Bridge: %s" % error, "err")
            return
        added, offered = self.merge_replies(replies)
        self.db["settings"]["bridge_last_sync"] = \
            datetime.now().isoformat(timespec="seconds")
        self.persist()
        self.refresh_bridge_note()
        self.refresh_bridge_status()
        # every reply that brought a PDF or a scan is now opened and read
        self.read_reply_documents(quiet=True)
        if quiet and not added:
            return
        self.toast("Bridge synced: %d new repl%s (%d already on record)."
                   % (added, "y" if added == 1 else "ies", offered - added),
                   "ok")

    def refresh_bridge_note(self):
        if not hasattr(self, "bridge_note"):
            return
        url = (self.db["settings"].get("bridge_feed_url") or "").strip()
        stamp = self.db["settings"].get("bridge_last_sync") or ""
        if not url:
            self.bridge_note.setText("Gmail bridge not connected")
        elif stamp:
            self.bridge_note.setText("Bridge last read %s" % stamp_text(stamp))
        else:
            self.bridge_note.setText("Bridge connected, not yet read")

    # ------------------------------------------- reading the reply's document
    def unread_document_replies(self, retry=False):
        """Replies of this engagement whose PDF or scan has not been read."""
        return [r for r in self.stored_replies()
                if reply_has_unread_files(r) and
                (retry or not r.get("files_error"))]

    def refresh_reader_note(self, text=None):
        if not hasattr(self, "reader_note"):
            return
        if text is None:
            ready, words = reader_status()
            waiting = len(self.unread_document_replies(retry=True))
            read = sum(1 for r in self.stored_replies() if r.get("files_read"))
            if ready:
                text = "%s. %d document%s read, %d waiting." % (
                    words, read, "" if read == 1 else "s", waiting)
            else:
                text = words
        self.reader_note.setText(text)

    def read_reply_documents(self, quiet=False, retry=False):
        """Open every unread PDF or scan and take the confirmed amount from
        it.  Runs after each sync, and on demand from the button."""
        if getattr(self, "reader_thread", None):
            if not quiet:
                self.toast("Documents are already being read.", "warn")
            return
        waiting = self.unread_document_replies(retry=retry)
        if not waiting:
            if not quiet:
                self.toast("No reply has a PDF or scan left to read.", "info")
            self.refresh_reader_note()
            return
        ready, words = reader_status()
        if not ready:
            self.refresh_reader_note(words)
            if not quiet:
                self.toast(words, "warn")
            return
        url = (self.db["settings"].get("bridge_feed_url") or "").strip()
        if not url.lower().startswith("https://"):
            if not quiet:
                self.toast("The documents are fetched through the Gmail "
                           "bridge, which is not connected. Use \"Add a reply "
                           "from a PDF or scan\" for a file you hold.", "warn")
            return
        self.btn_read_docs.setEnabled(False)
        self.refresh_reader_note("Reading %d document%s…" % (
            len(waiting), "" if len(waiting) == 1 else "s"))
        self.reader_thread = QThread(self)
        self.reader_worker = DocumentWorker(url, [r["id"] for r in waiting])
        self.reader_worker.moveToThread(self.reader_thread)
        self.reader_thread.started.connect(self.reader_worker.run)
        self.reader_worker.progress.connect(self.on_document_read)
        self.reader_worker.finished.connect(self.on_documents_finished)
        self.reader_thread.start()

    def store_reading(self, reply, entries, error=""):
        """Keep what was read with the reply it belongs to."""
        names = {entry["name"] for entry in entries}
        kept = [a for a in (reply.get("attachments") or [])
                if not (a.get("read_by") == "application" and
                        a.get("name") in names)]
        # what this computer read goes first: it is the fuller reading
        reply["attachments"] = [e for e in entries if e.get("text")] + kept
        problems = [e["name"] + ": " + e["error"] for e in entries
                    if e.get("error") and not e.get("text")]
        if error:
            problems.append(error)
        reply["files_error"] = "; ".join(problems)
        reply["files_read"] = any(e.get("text") for e in entries)
        reply["files_read_at"] = datetime.now().isoformat(timespec="seconds")

    def on_document_read(self, reply_id, entries, error, number, total):
        for reply in self.db.get("replies", []):
            if reply.get("id") == reply_id:
                self.store_reading(reply, entries, error)
                break
        self.refresh_reader_note("Read %d of %d…" % (number, total))

    def on_documents_finished(self, done, failed):
        thread = getattr(self, "reader_thread", None)
        if thread:
            thread.quit()
            thread.wait(5000)
        self.reader_thread = None
        self.reader_worker = None
        self.btn_read_docs.setEnabled(True)
        self.persist()
        self.refresh_recon()
        text = "%d document%s read" % (done, "" if done == 1 else "s")
        if failed:
            text += "; %d could not be read (see the exception queue)" % failed
        self.toast(text + ".", "warn" if failed else "ok")

    def add_reply_from_file(self, path=None):
        """A confirmation that did not come through the mailbox: the file is
        read here and matched to its party by reference code or name."""
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, "The confirmation received", "",
                "PDFs and scans (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp)")
        if not path:
            return None
        ready, words = reader_status()
        if not ready:
            self.toast(words, "warn")
            return None
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except Exception as exc:
            self.toast("The file could not be opened: %s" % exc, "err")
            return None
        name = os.path.basename(path)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            reading = read_document(data, name)
        finally:
            QApplication.restoreOverrideCursor()
        if not reading.get("text"):
            self.toast("Nothing could be read from %s: %s"
                       % (name, reading.get("error") or "no text found"), "err")
            return None
        client, year = self.active_client(), self.active_fy()
        reply = {
            "id": "file-" + new_id(),
            "received_at": date.today().isoformat(),
            "from_email": "", "from_name": "",
            "subject": "Received as a file: " + name,
            "body": "", "thread_id": "", "in_reply_to": "",
            "reference": find_reference(reading["text"]) or "",
            "bounced": False, "manual": True,
            "client_id": client["id"] if client else None,
            "fy_id": year["id"] if year else None,
            "files": [name], "files_read": True, "files_error": "",
            "attachments": [attachment_entry(name, reading)],
        }
        self.db.setdefault("replies", []).append(reply)
        self.persist()
        self.refresh_recon()
        row = next((r for r in self.recon_rows
                    if r.get("extract_source") == name or
                    (reply["reference"] and
                     r.get("reference") == reply["reference"] and
                     r.get("received_at"))), None)
        if row:
            self.toast("%s read (%s) and matched to %s: %s."
                       % (name, reading["method"], row["party_name"],
                          row["status"]), "ok")
        else:
            self.toast("%s was read but could not be matched to a party; it "
                       "is in the exception queue." % name, "warn")
        return reply
