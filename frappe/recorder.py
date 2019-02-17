# -*- coding: utf-8 -*-
# Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt
from __future__ import unicode_literals

import json
import time
import traceback
import frappe
import sqlparse
import datetime


RECORDER_INTERCEPT_FLAG = "recorder-intercept"
RECORDER_REQUEST_SPARSE_HASH = "recorder-requests-sparse"
RECORDER_REQUEST_HASH = "recorder-requests"


def sql(*args, **kwargs):
	start_time = time.time()
	result = frappe.db._sql(*args, **kwargs)
	end_time = time.time()

	stack = "".join(traceback.format_stack())

	query = frappe.db._cursor._executed
	query = sqlparse.format(query.strip(), keyword_case="upper", reindent=True)
	data = {
		"query": query,
		"stack": stack,
		"time": start_time,
		"duration": float("{:.3f}".format((end_time - start_time) * 1000)),
	}

	frappe.local._recorder.register(data)
	return result


def record():
	if frappe.cache().get_value(RECORDER_INTERCEPT_FLAG):
		frappe.local._recorder = Recorder()


def dump():
	if hasattr(frappe.local, "_recorder"):
		frappe.local._recorder.dump()


class Recorder():
	def __init__(self):
		self.uuid = frappe.generate_hash(length=10)
		self.time = datetime.datetime.now()
		self.calls = []
		self.path = frappe.request.path
		self.cmd = frappe.local.form_dict.cmd or ""
		self.method = frappe.request.method
		self.headers = dict(frappe.local.request.headers)
		self.form_dict = frappe.local.form_dict
		_patch()

	def register(self, data):
		self.calls.append(data)

	def dump(self):
		request_data = {
			"uuid": self.uuid,
			"path": self.path,
			"cmd": self.cmd,
			"time": self.time,
			"queries": len(self.calls),
			"time_queries": float("{:0.3f}".format(sum(call["duration"] for call in self.calls))),
			"duration": float("{:0.3f}".format((datetime.datetime.now() - self.time).total_seconds() * 1000)),
			"method": self.method,
		}
		frappe.cache().hset(RECORDER_REQUEST_SPARSE_HASH, self.uuid, request_data)
		frappe.publish_realtime(event="recorder-dump-event", message=json.dumps(request_data, default=str))

		request_data["calls"] = self.calls
		request_data["headers"] = self.headers
		request_data["form_dict"] = self.form_dict
		frappe.cache().hset(RECORDER_REQUEST_HASH, self.uuid, request_data)


def _patch():
	frappe.db._sql = frappe.db.sql
	frappe.db.sql = sql


def do_not_record(function):
	def wrapper(*args, **kwargs):
		if hasattr(frappe.local, "_recorder"):
			del frappe.local._recorder
			frappe.db.sql = frappe.db._sql
		return function(*args, **kwargs)
	return wrapper


@frappe.whitelist()
@do_not_record
def status(*args, **kwargs):
	return bool(frappe.cache().get_value(RECORDER_INTERCEPT_FLAG))


@frappe.whitelist()
@do_not_record
def start(*args, **kwargs):
	frappe.cache().set_value(RECORDER_INTERCEPT_FLAG, 1)


@frappe.whitelist()
@do_not_record
def stop(*args, **kwargs):
	frappe.cache().delete_value(RECORDER_INTERCEPT_FLAG)


@frappe.whitelist()
@do_not_record
def get(uuid=None, *args, **kwargs):
	if uuid:
		result = frappe.cache().hget(RECORDER_REQUEST_HASH, uuid)
	else:
		result = frappe.cache().hgetall(RECORDER_REQUEST_SPARSE_HASH).values()
	return result


@frappe.whitelist()
@do_not_record
def delete(*args, **kwargs):
	frappe.cache().delete_value(RECORDER_REQUEST_SPARSE_HASH)
	frappe.cache().delete_value(RECORDER_REQUEST_HASH)
