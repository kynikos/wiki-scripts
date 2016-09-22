#!/usr/bin/env python3

import random
import logging

from sqlalchemy import bindparam

import ws.utils
from ws.parser_helpers.title import Title
from ws.client.api import ShortRecentChangesError

from . import Grabber

logger = logging.getLogger(__name__)

class GrabberPages(Grabber):

    TARGET_TABLES = ["page", "page_props", "page_restrictions"]

    def __init__(self, api, db):
        super().__init__(api, db)

        self.sql = {
            ("insert", "page"):
                db.page.insert(mysql_on_duplicate_key_update=[
                    db.page.c.page_namespace,
                    db.page.c.page_title,
                    db.page.c.page_is_redirect,
                    db.page.c.page_is_new,
                    db.page.c.page_random,
                    db.page.c.page_touched,
                    db.page.c.page_links_updated,
                    db.page.c.page_latest,
                    db.page.c.page_len,
                    db.page.c.page_content_model,
                    db.page.c.page_lang,
                ]),
            ("insert", "page_props"):
                db.page_props.insert(mysql_on_duplicate_key_update=[
                    db.page_props.c.pp_value,
                ]),
            ("insert", "page_restrictions"):
                db.page_restrictions.insert(mysql_on_duplicate_key_update=[
                    db.page_restrictions.c.pr_level,
                    db.page_restrictions.c.pr_cascade,
                    db.page_restrictions.c.pr_user,
                    db.page_restrictions.c.pr_expiry,
                ]),
            ("delete", "page"):
                db.page.delete().where(db.page.c.page_id == bindparam("b_page_id")),
            ("delete", "page_props"):
                db.page_props.delete().where(
                    db.page_props.c.pp_page == bindparam("b_pp_page")),
            ("delete", "page_restrictions"):
                db.page_restrictions.delete().where(
                    db.page_restrictions.c.pr_page == bindparam("b_pr_page")),
        }


    def gen_inserts_from_page(self, page):
        if "missing" in page:
            raise StopIteration

        title = Title(self.api, page["title"])

        # items for page table
        db_entry = {
            "page_id": page["pageid"],
            "page_namespace": page["ns"],
            # title is stored without the namespace prefix
            "page_title": title.pagename,
            "page_is_redirect": "redirect" in page,
            "page_is_new": "new" in page,
            "page_random": random.random(),
            "page_touched": page["touched"],
            "page_links_updated": None,
            "page_latest": page["lastrevid"],
            "page_len": page["length"],
            "page_content_model": page["contentmodel"],
            "page_lang": page["pagelanguage"],
        }
        yield self.sql["insert", "page"], db_entry

        # items for page_props table
        for propname, value in page.get("pageprops", {}).items():
            db_entry = {
                "pp_page": page["pageid"],
                "pp_propname": propname,
                "pp_value": value,
                # TODO: how should this be populated?
#                "pp_sortkey":
            }
            yield self.sql["insert", "page_props"], db_entry

        # items for page_restrictions table
        for pr in page["protection"]:
            # drop entries caused by cascading protection
            if "source" not in pr:
                db_entry = {
                    "pr_page": page["pageid"],
                    "pr_type": pr["type"],
                    "pr_level": pr["level"],
                    "pr_cascade": "cascade" in pr,
                    "pr_user": None,    # unused
                    "pr_expiry": pr["expiry"],
                }
                yield self.sql["insert", "page_restrictions"], db_entry


    def gen_deletes_from_page(self, page):
        if "missing" in page:
            # deleted page - this will cause cascade deletion in
            # page_props and page_restrictions tables
            yield self.sql["delete", "page"], {"b_page_id": page["pageid"]}
        else:
            # delete outdated props
            props = set(page.get("pageprops", {}))
            if props:
                # we need to check a tuple of arbitrary length (i.e. the props to keep),
                # so the queries can't be grouped
                yield self.db.page_props.delete().where(
                        (self.db.page_props.c.pp_page == page["pageid"]) &
                        self.db.page_props.c.pp_propname.notin_(props))
            else:
                # no props present - delete all rows with the pageid
                yield self.sql["delete", "page_props"], {"b_pp_page": page["pageid"]}

            # delete outdated restrictions
            applied = set(pr["type"] for pr in page["protection"])
            if applied:
                # we need to check a tuple of arbitrary length (i.e. the restrictions
                # to keep), so the queries can't be grouped
                yield self.db.page_restrictions.delete().where(
                        (self.db.page_restrictions.c.pr_page == page["pageid"]) &
                        self.db.page_restrictions.c.pr_type.notin_(applied))
            else:
                # no restrictions applied - delete all rows with the pageid
                yield self.sql["delete", "page_restrictions"], {"b_pr_page": page["pageid"]}


    def gen_insert(self):
        params = {
            "generator": "allpages",
            "gaplimit": "max",
            "prop": "info|pageprops",
            "inprop": "protection",
        }
        for ns in self.api.site.namespaces.keys():
            if ns < 0:
                continue
            params["gapnamespace"] = ns
            for page in self.api.generator(params):
                yield from self.gen_inserts_from_page(page)


    def gen_update(self, since):
        rcpages = self.get_rcpages(since)
        if rcpages:
            logger.info("Fetching properties of {} modified pages...".format(len(rcpages)))
            for chunk in ws.utils.iter_chunks(rcpages, self.api.max_ids_per_query):
                params = {
                    "action": "query",
                    "pageids": "|".join(str(pageid) for pageid in chunk),
                    "prop": "info|pageprops",
                    "inprop": "protection",
                }
                for page in self.api.call_api(params)["pages"].values():
                    yield from self.gen_inserts_from_page(page)
                    yield from self.gen_deletes_from_page(page)


    def get_rcpages(self, since):
        since_f = ws.utils.format_date(since)
        rcpages = set()

        # Items in the recentchanges table are periodically purged according to
        # http://www.mediawiki.org/wiki/Manual:$wgRCMaxAge
        # By default the max age is 13 weeks: if a larger timespan is requested
        # here, it's very important to warn that the changes are not available
        if self.api.oldest_recent_change > since:
            raise ShortRecentChangesError()

        rc_params = {
            "action": "query",
            "list": "recentchanges",
            "rctype": "edit|new|log",
            "rcprop": "ids",
            "rclimit": "max",
            "rcdir": "newer",
            "rcstart": since_f,
        }
        for change in self.api.list(rc_params):
            # add pageid for edits, new pages and target pages of log events
            rcpages.add(change["pageid"])

            # TODO: examine logs (needs rcprop=loginfo)
            # move, protect, delete are handled by the above
            # these deserve special treatment
            #   merge       (revision - or maybe page too?)
            #   import      (everything?)
            #   patrol      (page)  (not in recentchanges! so we can't know when a page loses its 'new' flag)
            #   suppress    (everything?)
#            if change["type"] == "log":
#                if change["logtype"] == "merge":
#                    ...

        return rcpages
