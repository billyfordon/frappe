# Copyright (c) 2013, Web Notes Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt 

from __future__ import unicode_literals
import frappe, json, os
from frappe.utils import cint, now, cstr
from frappe import throw, msgprint, _
from frappe.auth import _update_password

STANDARD_USERS = ("Guest", "Administrator")

class DocType:
	def __init__(self, doc, doclist):
		self.doc = doc
		self.doclist = doclist
		
	def autoname(self):
		"""set name as email id"""
		if self.doc.name not in STANDARD_USERS:
			self.doc.email = self.doc.email.strip()		
			self.doc.name = self.doc.email
			
			if frappe.db.exists("User", self.doc.name):
				throw(_("Name Exists"))

	def validate(self):
		self.in_insert = self.doc.fields.get("__islocal")
		if self.doc.name not in STANDARD_USERS:
			self.validate_email_type(self.doc.email)
		self.add_system_manager_role()
		self.check_enable_disable()
		self.update_gravatar()

	def check_enable_disable(self):
		# do not allow disabling administrator/guest
		if not cint(self.doc.enabled) and self.doc.name in STANDARD_USERS:
			throw("{msg}: {name}".format(**{
				"msg": _("Hey! You cannot disable user"), 
				"name": self.doc.name
			}))

		if not cint(self.doc.enabled):
			self.a_system_manager_should_exist()
		
		# clear sessions if disabled
		if not cint(self.doc.enabled) and getattr(frappe, "login_manager", None):
			frappe.local.login_manager.logout(user=self.doc.name)
		
	def add_system_manager_role(self):
		# if adding system manager, do nothing
		if not cint(self.doc.enabled) or ("System Manager" in [user_role.role for user_role in
				self.doclist.get({"parentfield": "user_roles"})]):
			return
		
		if self.doc.user_type == "System User" and not self.get_other_system_managers():
			msgprint("""Adding System Manager Role as there must 
				be atleast one 'System Manager'.""")
			self.doclist.append({
				"doctype": "UserRole",
				"parentfield": "user_roles",
				"role": "System Manager"
			})
	
	def email_new_password(self):
		if self.doc.new_password and not self.in_insert:
			_update_password(self.doc.name, self.doc.new_password)

			self.password_update_mail(self.doc.new_password)
			frappe.msgprint("New Password Emailed.")
			
	def on_update(self):
		# owner is always name
		frappe.db.set(self.doc, 'owner', self.doc.name)
		frappe.clear_cache(user=self.doc.name)
		
		try:
			if self.in_insert:
				if self.doc.name not in STANDARD_USERS:
					if self.doc.new_password:
						# new password given, no email required
						_update_password(self.doc.name, self.doc.new_password)
					if not getattr(self, "no_welcome_mail", False):
						self.send_welcome_mail()
						msgprint(_("Welcome Email Sent"))
			else:
				self.email_new_password()

		except frappe.OutgoingEmailError:
			pass # email server not set, don't send email

		self.doc.set("new_password", "")
		
	def update_gravatar(self):
		import md5
		if not self.doc.user_image:
			self.doc.user_image = "https://secure.gravatar.com/avatar/" + md5.md5(self.doc.name).hexdigest() \
				+ "?d=retro"
	
	def reset_password(self):
		from frappe.utils import random_string, get_url

		key = random_string(32)
		frappe.db.set_value("User", self.doc.name, "reset_password_key", key)
		self.password_reset_mail(get_url("/update-password?key=" + key))
	
	def get_other_system_managers(self):
		return frappe.db.sql("""select distinct parent from tabUserRole user_role
			where role='System Manager' and docstatus<2
			and parent not in ('Administrator', %s) and exists 
				(select * from `tabUser` user 
				where user.name=user_role.parent and enabled=1)""", (self.doc.name,))

	def get_fullname(self):
		"""get first_name space last_name"""
		return (self.doc.first_name or '') + \
			(self.doc.first_name and " " or '') + (self.doc.last_name or '')

	def password_reset_mail(self, link):
		self.send_login_mail("Password Reset", "templates/emails/password_reset.html", {"link": link})
	
	def password_update_mail(self, password):
		self.send_login_mail("Password Update", "templates/emails/password_update.html", {"new_password": password})

	def send_welcome_mail(self):
		from frappe.utils import random_string, get_url

		self.doc.reset_password_key = random_string(32)
		link = get_url("/update-password?key=" + self.doc.reset_password_key)

		self.send_login_mail("Verify Your Account", "templates/emails/new_user.html", {"link": link})
		
	def send_login_mail(self, subject, template, add_args):
		"""send mail with login details"""
		from frappe.utils.user import get_user_fullname
		from frappe.utils import get_url
		
		mail_titles = frappe.get_hooks().get("login_mail_title", [])
		title = frappe.db.get_default('company') or (mail_titles and mail_titles[0]) or ""
		
		full_name = get_user_fullname(frappe.session['user'])
		if full_name == "Guest":
			full_name = "Administrator"
	
		args = {
			'first_name': self.doc.first_name or self.doc.last_name or "user",
			'user': self.doc.name,
			'title': title,
			'login_url': get_url(),
			'user_fullname': full_name
		}
		
		args.update(add_args)
		
		sender = frappe.session.user not in STANDARD_USERS and frappe.session.user or None
		
		frappe.sendmail(recipients=self.doc.email, sender=sender, subject=subject, 
			message=frappe.get_template(template).render(args))
		
	def a_system_manager_should_exist(self):
		if not self.get_other_system_managers():
			throw(_("Hey! There should remain at least one System Manager"))
		
	def on_trash(self):
		frappe.clear_cache(user=self.doc.name)
		if self.doc.name in STANDARD_USERS:
			throw("{msg}: {name}".format(**{
				"msg": _("Hey! You cannot delete user"), 
				"name": self.doc.name
			}))
		
		self.a_system_manager_should_exist()
				
		# disable the user and log him/her out
		self.doc.enabled = 0
		if getattr(frappe.local, "login_manager", None):
			frappe.local.login_manager.logout(user=self.doc.name)
		
		# delete their password
		frappe.db.sql("""delete from __Auth where user=%s""", (self.doc.name,))
		
		# delete todos
		frappe.db.sql("""delete from `tabToDo` where owner=%s""", (self.doc.name,))
		frappe.db.sql("""update tabToDo set assigned_by=null where assigned_by=%s""",
			(self.doc.name,))
		
		# delete events
		frappe.db.sql("""delete from `tabEvent` where owner=%s
			and event_type='Private'""", (self.doc.name,))
		frappe.db.sql("""delete from `tabEvent User` where person=%s""", (self.doc.name,))
			
		# delete messages
		frappe.db.sql("""delete from `tabComment` where comment_doctype='Message'
			and (comment_docname=%s or owner=%s)""", (self.doc.name, self.doc.name))
			
	def before_rename(self, olddn, newdn, merge=False):
		frappe.clear_cache(user=olddn)
		self.validate_rename(olddn, newdn)
	
	def validate_rename(self, olddn, newdn):
		# do not allow renaming administrator and guest
		if olddn in STANDARD_USERS:
			throw("{msg}: {name}".format(**{
				"msg": _("Hey! You are restricted from renaming the user"), 
				"name": olddn
			}))
		
		self.validate_email_type(newdn)
	
	def validate_email_type(self, email):
		from frappe.utils import validate_email_add
	
		email = email.strip()
		if not validate_email_add(email):
			throw("{email} {msg}".format(**{
				"email": email, 
				"msg": _("is not a valid email id")
			}))
	
	def after_rename(self, olddn, newdn, merge=False):			
		tables = frappe.db.sql("show tables")
		for tab in tables:
			desc = frappe.db.sql("desc `%s`" % tab[0], as_dict=1)
			has_fields = []
			for d in desc:
				if d.get('Field') in ['owner', 'modified_by']:
					has_fields.append(d.get('Field'))
			for field in has_fields:
				frappe.db.sql("""\
					update `%s` set `%s`=%s
					where `%s`=%s""" % \
					(tab[0], field, '%s', field, '%s'), (newdn, olddn))
					
		# set email
		frappe.db.sql("""\
			update `tabUser` set email=%s
			where name=%s""", (newdn, newdn))
		
		# update __Auth table
		if not merge:
			frappe.db.sql("""update __Auth set user=%s where user=%s""", (newdn, olddn))
			
	def add_roles(self, *roles):
		for role in roles:
			if role in [d.role for d in self.doclist.get({"doctype":"UserRole"})]:
				continue
			self.bean.doclist.append({
				"doctype": "UserRole",
				"parentfield": "user_roles",
				"role": role
			})
			
		self.bean.save()

@frappe.whitelist()
def get_languages():
	from frappe.translate import get_lang_dict
	languages = get_lang_dict().keys()
	languages.sort()
	return [""] + languages

@frappe.whitelist()
def get_all_roles(arg=None):
	"""return all roles"""
	return [r[0] for r in frappe.db.sql("""select name from tabRole
		where name not in ('Administrator', 'Guest', 'All') order by name""")]
		
@frappe.whitelist()
def get_user_roles(arg=None):
	"""get roles for a user"""
	return frappe.get_roles(frappe.form_dict['uid'])

@frappe.whitelist()
def get_perm_info(arg=None):
	"""get permission info"""
	return frappe.db.sql("""select parent, permlevel, `read`, `write`, submit,
		cancel, amend from tabDocPerm where role=%s 
		and docstatus<2 order by parent, permlevel""", 
			(frappe.form_dict['role'],), as_dict=1)

@frappe.whitelist(allow_guest=True)
def update_password(new_password, key=None, old_password=None):
	# verify old password
	if key:
		user = frappe.db.get_value("User", {"reset_password_key":key})
		if not user:
			return _("Cannot Update: Incorrect / Expired Link.")
	elif old_password:
		user = frappe.session.user
		if not frappe.db.sql("""select user from __Auth where password=password(%s) 
			and user=%s""", (old_password, user)):
			return _("Cannot Update: Incorrect Password")
	
	_update_password(user, new_password)
	
	frappe.db.set_value("User", user, "reset_password_key", "")
	
	frappe.local.login_manager.logout()
	
	return _("Password Updated")
	
@frappe.whitelist(allow_guest=True)
def sign_up(email, full_name):
	user = frappe.db.get("User", {"email": email})
	if user:
		if user.disabled:
			return _("Registered but disabled.")
		else:
			return _("Already Registered")
	else:
		if frappe.db.sql("""select count(*) from tabUser where 
			TIMEDIFF(%s, modified) > '1:00:00' """, now())[0][0] > 200:
			raise Exception, "Too Many New Users"
		from frappe.utils import random_string
		user = frappe.bean({
			"doctype":"User",
			"email": email,
			"first_name": full_name,
			"enabled": 1,
			"new_password": random_string(10),
			"user_type": "Website User"
		})
		user.ignore_permissions = True
		user.insert()
		return _("Registration Details Emailed.")

@frappe.whitelist(allow_guest=True)
def reset_password(user):	
	user = frappe.form_dict.get('user', '')
	if user in ["demo@erpnext.com", "Administrator"]:
		return "Not allowed"
		
	if frappe.db.sql("""select name from tabUser where name=%s""", (user,)):
		# Hack!
		frappe.session["user"] = "Administrator"
		user = frappe.bean("User", user)
		user.get_controller().reset_password()
		return "Password reset details sent to your email."
	else:
		return "No such user (%s)" % user
		
def user_query(doctype, txt, searchfield, start, page_len, filters):
	from frappe.widgets.reportview import get_match_cond
	txt = "%{}%".format(txt)
	return frappe.db.sql("""select name, concat_ws(' ', first_name, middle_name, last_name) 
		from `tabUser` 
		where ifnull(enabled, 0)=1 
			and docstatus < 2 
			and name not in ({standard_users}) 
			and user_type != 'Website User'
			and ({key} like %s
				or concat_ws(' ', first_name, middle_name, last_name) like %s) 
			{mcond}
		order by 
			case when name like %s then 0 else 1 end, 
			case when concat_ws(' ', first_name, middle_name, last_name) like %s 
				then 0 else 1 end, 
			name asc 
		limit %s, %s""".format(standard_users=", ".join(["%s"]*len(STANDARD_USERS)),
			key=searchfield, mcond=get_match_cond(doctype)), 
			tuple(list(STANDARD_USERS) + [txt, txt, txt, txt, start, page_len]))

def get_total_users(exclude_users=None):
	"""Returns total no. of system users"""
	return len(get_system_users(exclude_users=exclude_users))
	
def get_system_users(exclude_users=None):
	if not exclude_users:
		exclude_users = []
	elif not isinstance(exclude_users, (list, tuple)):
		exclude_users = [exclude_users]
	
	exclude_users += list(STANDARD_USERS)
	
	system_users = frappe.db.sql_list("""select name from `tabUser` 
		where enabled=1 and user_type != 'Website User' 
		and name not in ({})""".format(", ".join(["%s"]*len(exclude_users))),
		exclude_users)

	return system_users

def get_active_users():
	"""Returns No. of system users who logged in, in the last 3 days"""
	return frappe.db.sql("""select count(*) from `tabUser`
		where enabled = 1 and user_type != 'Website User'
		and name not in ({})
		and hour(timediff(now(), last_login)) < 72""".format(", ".join(["%s"]*len(STANDARD_USERS))), STANDARD_USERS)[0][0]

def get_website_users():
	"""Returns total no. of website users"""
	return frappe.db.sql("""select count(*) from `tabUser`
		where enabled = 1 and user_type = 'Website User'""")[0][0]
	
def get_active_website_users():
	"""Returns No. of website users who logged in, in the last 3 days"""
	return frappe.db.sql("""select count(*) from `tabUser`
		where enabled = 1 and user_type = 'Website User'
		and hour(timediff(now(), last_login)) < 72""")[0][0]

