# Copyright (c) 2013, Web Notes Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt

from __future__ import unicode_literals
"""build query for doclistview and return results"""

import frappe, json
import frappe.permissions
from frappe.model.db_query import DatabaseQuery

@frappe.whitelist()
def get():
	return compress(execute(**get_form_params()))

def execute(doctype, query=None, filters=None, fields=None, docstatus=None, 
		group_by=None, order_by=None, limit_start=0, limit_page_length=20, 
		as_list=False, with_childnames=False, debug=False):
	return DatabaseQuery(doctype).execute(query, filters, fields, docstatus, group_by,
		order_by, limit_start, limit_page_length, as_list, with_childnames, debug)

def get_form_params():
	data = frappe._dict(frappe.local.form_dict)

	del data["cmd"]

	if isinstance(data.get("filters"), basestring):
		data["filters"] = json.loads(data["filters"])
	if isinstance(data.get("fields"), basestring):
		data["fields"] = json.loads(data["fields"])
	if isinstance(data.get("docstatus"), basestring):
		data["docstatus"] = json.loads(data["docstatus"])
		
	return data
		
def compress(data):
	"""separate keys and values"""
	if not data: return data
	values = []
	keys = data[0].keys()
	for row in data:
		new_row = []
		for key in keys:
			new_row.append(row[key])
		values.append(new_row)
		
	return {
		"keys": keys,
		"values": values
	}
		
		
@frappe.whitelist()
def save_report():
	"""save report"""
	from frappe.model.doc import Document
	
	data = frappe.local.form_dict
	if frappe.db.exists('Report', data['name']):
		d = Document('Report', data['name'])
	else:
		d = Document('Report')
		d.report_name = data['name']
		d.ref_doctype = data['doctype']
	
	d.report_type = "Report Builder"
	d.json = data['json']
	frappe.bean([d]).save()
	frappe.msgprint("%s saved." % d.name)
	return d.name

@frappe.whitelist()
def export_query():
	"""export from report builder"""
	form_params = get_form_params()
	form_params["limit_page_length"] = None
	
	frappe.permissions.can_export(form_params.doctype, raise_exception=True)
	
	ret = execute(**form_params)

	columns = [x[0] for x in frappe.db.get_description()]
	data = [['Sr'] + get_labels(columns),]

	# flatten dict
	cnt = 1
	for row in ret:
		flat = [cnt,]
		for c in columns:
			flat.append(row.get(c))
		data.append(flat)
		cnt += 1

	# convert to csv
	from cStringIO import StringIO
	import csv

	f = StringIO()
	writer = csv.writer(f)
	for r in data:
		# encode only unicode type strings and not int, floats etc.
		writer.writerow(map(lambda v: isinstance(v, unicode) and v.encode('utf-8') or v, r))

	f.seek(0)
	frappe.response['result'] = unicode(f.read(), 'utf-8')
	frappe.response['type'] = 'csv'
	frappe.response['doctype'] = [t[4:-1] for t in self.tables][0]

def get_labels(columns):
	"""get column labels based on column names"""
	label_dict = {}
	for doctype in self.meta:
		for d in self.meta[doctype]:
			if d.doctype=='DocField' and d.fieldname:
				label_dict[d.fieldname] = d.label
	
	return map(lambda x: label_dict.get(x, x.title()), columns)

@frappe.whitelist()
def delete_items():
	"""delete selected items"""
	import json
	from frappe.model.code import get_obj

	il = json.loads(frappe.form_dict.get('items'))
	doctype = frappe.form_dict.get('doctype')
	
	for d in il:
		try:
			dt_obj = get_obj(doctype, d)
			if hasattr(dt_obj, 'on_trash'):
				dt_obj.on_trash()
			frappe.delete_doc(doctype, d)
		except Exception, e:
			frappe.errprint(frappe.get_traceback())
			pass
		
@frappe.whitelist()
def get_stats(stats, doctype):
	"""get tag info"""
	import json
	tags = json.loads(stats)
	stats = {}
	
	columns = frappe.db.get_table_columns(doctype)
	for tag in tags:
		if not tag in columns: continue
		tagcount = execute(doctype, fields=[tag, "count(*)"], 
			filters=["ifnull(%s,'')!=''" % tag], group_by=tag, as_list=True)
			
		if tag=='_user_tags':
			stats[tag] = scrub_user_tags(tagcount)
		else:
			stats[tag] = tagcount
			
	return stats

def scrub_user_tags(tagcount):
	"""rebuild tag list for tags"""
	rdict = {}
	tagdict = dict(tagcount)
	for t in tagdict:
		alltags = t.split(',')
		for tag in alltags:
			if tag:
				if not tag in rdict:
					rdict[tag] = 0
			
				rdict[tag] += tagdict[t]
	
	rlist = []
	for tag in rdict:
		rlist.append([tag, rdict[tag]])
	
	return rlist

# used in building query in queries.py
def get_match_cond(doctype):
	cond = DatabaseQuery(doctype).build_match_conditions()
	return (' and ' + cond) if cond else ""
	
def build_match_conditions(doctype, as_condition=True):
	return DatabaseQuery(doctype).build_match_conditions(as_condition=as_condition)
