# Copyright (c) 2013, Web Notes Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt 

import frappe
import frappe.utils, markdown2
from frappe.website.render import clear_cache

from frappe import _

@frappe.whitelist(allow_guest=True)
def add_comment(args=None):
	"""
		args = {
			'comment': '',
			'comment_by': '',
			'comment_by_fullname': '',
			'comment_doctype': '',
			'comment_docname': '',
			'page_name': '',
		}
	"""
	
	if not args: 
		args = frappe.local.form_dict
	args['doctype'] = "Comment"

	page_name = args.get("page_name")
	if "page_name" in args:
		del args["page_name"]
	if "cmd" in args:
		del args["cmd"]

	comment = frappe.bean(args)
	comment.ignore_permissions = True
	comment.insert()
	
	# since comments are embedded in the page, clear the web cache
	clear_cache(page_name)

	# notify commentors 
	commentors = [d[0] for d in frappe.db.sql("""select comment_by from tabComment where
		comment_doctype=%s and comment_docname=%s and
		ifnull(unsubscribed, 0)=0""", (comment.doc.comment_doctype, comment.doc.comment_docname))]
	
	owner = frappe.db.get_value(comment.doc.comment_doctype, comment.doc.comment_docname, "owner")
	recipients = commentors if owner=="Administrator" else list(set(commentors + [owner]))
	
	
	from frappe.utils.email_lib.bulk import send
	send(recipients=recipients, 
		doctype='Comment', 
		email_field='comment_by', 
		subject='New Comment on %s: %s' % (comment.doc.comment_doctype, 
			comment.doc.title or comment.doc.comment_docname), 
		message='%(comment)s<p>By %(comment_by_fullname)s</p>' % args,
		ref_doctype=comment.doc.comment_doctype, ref_docname=comment.doc.comment_docname)
	
	template = frappe.get_template("templates/includes/comment.html")
	
	return template.render({"comment": comment.doc.fields})
	