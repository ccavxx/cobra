#!/usr/bin/env python
#
# Copyright 2016 Feei. All Rights Reserved
#
# Author:   Feei <wufeifei@wufeifei.com>
# Homepage: https://github.com/wufeifei/cobra
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
# See the file 'doc/COPYING' for copying permission
#
import os
import sys
import subprocess

from flask import Flask
from flask_script import Manager, Server, Option, Command
from flask_sqlalchemy import SQLAlchemy
from flask_bootstrap import Bootstrap
from sqlalchemy import exc

from utils import log, config, common

reload(sys)
sys.setdefaultencoding('utf-8')

template = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
asset = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates/asset')
web = Flask(__name__, template_folder=template, static_folder=asset)

web.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = True
web.config['SQLALCHEMY_DATABASE_URI'] = config.Config('database', 'mysql').value
web.secret_key = config.Config('cobra', 'secret_key').value

bootstrap = Bootstrap(web)

# set bootstrap css and jquery js to local
web.config['BOOTSTRAP_SERVE_LOCAL'] = True

db = SQLAlchemy(web)

# just use the migration script's app context when you import the models
# http://stackoverflow.com/questions/33905706/flask-migrate-seemed-to-delete-all-my-database-data
with web.app_context():
    from models import *

manager = Manager(web)


class Statistic(Command):
    option_list = (
        Option('--target', '-t', dest='target', help='directory'),
        Option('--tid', '-i', dest='tid', help='scan task id')
    )

    def run(self, target=None, tid=None):
        if target is None:
            log.critical("Please set --target param")
            sys.exit()
        if tid is None:
            log.critical("Please set --tid param")
            sys.exit()

        # Statistic Code
        p = subprocess.Popen(
            ['cloc', target], stdout=subprocess.PIPE)
        (output, err) = p.communicate()
        rs = output.split("\n")
        for r in rs:
            r_e = r.split()
            if len(r_e) > 3 and r_e[0] == 'SUM:':
                t = CobraTaskInfo.query.filter_by(id=tid).first()
                if t is not None:
                    t.code_number = r_e[4]
                    try:
                        db.session.add(t)
                        db.session.commit()
                        log.info("Statistic code number done")
                    except Exception as e:
                        log.error("Statistic code number failed" + str(e.message))


class Scan(Command):
    option_list = (
        Option('--target', '-t', dest='target', help='scan target(directory/git repository/svn url/file path)'),
        Option('--tid', '-i', dest='tid', help='scan task id'),
        Option('--pid', '-p', dest='pid', help='scan project id'),
    )

    def parse_target(self, target=None):
        if target[len(target) - 4:] == '.git':
            return 'git'
        elif os.path.isdir(target) is True:
            return 'directory'
        elif os.path.isfile(target) is True:
            filename, file_extension = os.path.splitext(target)
            if file_extension in ['.tar.gz', '.rar', '.zip']:
                return 'compress'
            else:
                return 'file'
        elif target[0:7] == 'http://' or target[0:8] == 'https://':
            return 'svn'
        else:
            return False

    def run(self, target=None, tid=None, pid=None):
        if target is None:
            log.critical("Please set --target param")
            sys.exit()
        if tid is not None:
            task_id = tid
            # Start Time For Task
            t = CobraTaskInfo.query.filter_by(id=tid).first()
            if t is None:
                log.critical("Task id doesn't exists.")
                sys.exit()
            if t.status not in [0, 1]:
                log.critical("Task Already Scan.")
                sys.exit()
            t.status = 1
            t.time_start = int(time.time())
            t.updated_at = time.strftime('%Y-%m-%d %X', time.localtime())
            try:
                db.session.add(t)
                db.session.commit()
            except Exception as e:
                log.error("Set start time failed" + str(e.message))
        else:
            task_id = None

        target_type = self.parse_target(target)
        if target_type is False:
            log.error("""
                Git Repository: must .git end
                SVN Repository: can http:// or https://
                Directory: must be local directory
                File: must be single file or tar.gz/zip/rar compress file
                """)
        from engine import static
        s = static.Static(target, task_id=task_id, project_id=pid)
        if target_type is 'directory':
            s.analyse()
        elif target_type is 'compress':
            from utils.decompress import Decompress
            # load an compressed file. only tar.gz, rar, zip supported.
            dc = Decompress(target)
            # decompress it. And there will create a directory named "222_test.tar".
            dc.decompress()
            s.analyse()
        elif target_type is 'file':
            s.analyse()
        elif target_type is 'git':
            from pickup.GitTools import Git
            g = Git(target, branch='master')
            g.get_repo()
            if g.clone() is True:
                s.analyse()
            else:
                log.critical("Git clone failed")
        elif target_type is 'svn':
            log.warning("Not Support SVN Repository")


class Install(Command):
    def run(self):
        # create database structure
        log.debug("Start create database structure...")
        try:
            db.create_all()
        except exc.SQLAlchemyError as e:
            log.critical("MySQL database error: {0}\nFAQ: {1}".format(e, 'https://github.com/wufeifei/cobra/wiki/Error#mysql'))
            sys.exit(0)
        log.debug("Create Structure Success.")
        # insert base data
        from app.models import CobraAuth, CobraLanguages, CobraAdminUser, CobraVuls
        # table `auth`
        log.debug('Insert api key...')
        auth = CobraAuth('manual', common.md5('CobraAuthKey'), 1)
        db.session.add(auth)

        # table `languages`
        log.debug('Insert language...')
        languages = {
            "php": ".php|.php3|.php4|.php5",
            "jsp": ".jsp",
            "java": ".java",
            "html": ".html|.htm|.phps|.phtml",
            "js": ".js",
            "backup": ".zip|.bak|.tar|.tar.gz|.rar",
            "xml": ".xml",
            "image": ".jpg|.png|.bmp|.gif|.ico|.cur",
            "font": ".eot|.otf|.svg|.ttf|.woff",
            "css": ".css|.less|.scss|.styl",
            "exe": ".exe",
            "shell": ".sh",
            "log": ".log",
            "text": ".txt|.text",
            "flash": ".swf",
            "yml": ".yml",
            "cert": ".p12|.crt|.key|.pfx|.csr",
            "psd": ".psd",
            "iml": ".iml",
            "spf": ".spf",
            "markdown": ".md",
            "office": ".doc|.docx|.wps|.rtf|.csv|.xls|.ppt",
            "bat": ".bat",
            "PSD": ".psd",
            "Thumb": ".db",
        }
        for language, extensions in languages.iteritems():
            a_language = CobraLanguages(language, extensions)
            db.session.add(a_language)

        # table `user`
        log.debug('Insert admin user...')
        username = 'admin'
        password = 'admin123456!@#'
        role = 1  # 1: super admin, 2: admin, 3: rules admin
        a_user = CobraAdminUser(username, password, role)
        db.session.add(a_user)

        # table `vuls`
        log.debug('Insert vuls...')
        vuls = [
            'SQL Injection',
            'LFI/RFI',
            'Header Injection',
            'XSS',
            'CSRF',
            'Logic Bug',
            'Command Execute',
            'Code Execute',
            'Information Disclosure',
            'Data Exposure',
            'Xpath Injection',
            'LDAP Injection',
            'XML/XXE Injection',
            'Unserialize',
            'Variables Override',
            'URL Redirect',
            'Weak Function',
            'Buffer Overflow',
            'Deprecated Function',
            'Stack Trace',
            'Resource Executable',
            'SSRF',
            'Misconfiguration',
            'Components'
        ]
        for vul in vuls:
            a_vul = CobraVuls(vul, 'Vul Description', 'Vul Repair')
            db.session.add(a_vul)

        # commit
        db.session.commit()
        log.debug('All Done.')


host = config.Config('cobra', 'host').value
port = config.Config('cobra', 'port').value
port = int(port)

manager.add_command('start', Server(host=host, port=port))
manager.add_command('scan', Scan())
manager.add_command('statistic', Statistic())
manager.add_command('install', Install())

# frontend and api
from app.controller import route
from app.controller import api

# backend
from app.controller.backend import BackendAPIController
from app.controller.backend import DashboardController
from app.controller.backend import IndexController
from app.controller.backend import LanguagesController
from app.controller.backend import ProjectsController
from app.controller.backend import RulesController
from app.controller.backend import SearchController
from app.controller.backend import TasksController
from app.controller.backend import VulsController
from app.controller.backend import WhiteListsController
