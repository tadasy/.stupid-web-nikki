#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import time
import pprint
import psycopg2
import datetime
import markdown
from flask import Flask, request, session, g, redirect, url_for, abort, render_template, flash


app = Flask(__name__)
app.config.update(DEBUG=bool(os.getenv('DEBUG')), SECRET_KEY=os.getenv('SECRET_KEY'))


def connect_db():
    return psycopg2.connect(database = os.getenv('PGSQL_DB'),
                            user     = os.getenv('PGSQL_USER'),
                            password = os.getenv('PGSQL_PASS'),
                            host     = os.getenv('PGSQL_HOST'),
                            port     = os.getenv('PGSQL_PORT'),
                            )


@app.template_filter('unicode')
def unicode_filter(s):
    return s.decode('utf-8')


@app.template_filter('day_of_week')
def day_of_week_filter(s):
    s = str(s)
    weeks = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
    return weeks[datetime.datetime(int(s[0:4]), int(s[4:6]), int(s[6:8])).weekday()]


@app.template_filter('date')
def date_filter(s):
    s = str(s)
    return s[0:4] + '/' + s[4:6] + '/' + s[6:8]


@app.template_filter('search_snippet')
def search_snippet_filter(text, search_word):
    snippet_len = 300
    snippet_prev_buffer = 10

    text_len = len(text)
    try:
        bottom_idx = text.index(search_word) - snippet_prev_buffer
        bottom_idx = 0 if (bottom_idx < 0) else bottom_idx
    except ValueError:
        bottom_idx = 0

    t = text_len - bottom_idx
    if (t < snippet_len):
        bottom_idx -= snippet_len - t
        bottom_idx = 0 if (bottom_idx < 0) else bottom_idx

    t = bottom_idx + snippet_len
    upper_idx = text_len if (text_len < t) else t

    return text[bottom_idx:upper_idx]


# @app.template_filter('emphasis')
# def emphasis_filter(text, search_word, tag='em'):
#     return text.replace(search_word, '<' + tag + '>' + search_word + '</' + tag + '>')


@app.before_request
def before_request():
    g.today = datetime.datetime.today()
    g.h1 = os.getenv('TITLE') # for <h1></h1> of each page
    g.db = connect_db()

    # if (request.url_root.startswith('http://') and
    #     (not app.config['DEBUG'])):
    #     return redirect(request.url.replace("http://", "https://", 1), 301)

    x_forwarded_for = request.headers.getlist("X-Forwarded-For")
    if ((not request.path.startswith('/static/')) and
        (not request.path.startswith('/favicon.ico')) and
        (not request.path.startswith('/api'))):
        cursor = g.db.cursor()
        cursor.execute('INSERT INTO access_log (path, ip_address, user_agent, referer, access_time) VALUES (%s, %s, %s, %s, %s)', \
                           [request.url[len(request.url_root) -1:],
                            x_forwarded_for[0] if (0 < len(x_forwarded_for))  else request.remote_addr,
                            request.headers['User-Agent'] if request.headers.has_key('User-Agent') else '',
                            request.headers['Referer'] if request.headers.has_key('Referer') else '',
                            int(time.time())])
        g.db.commit()

    try:
        g.login = session['login']
    except:
        g.login = False


@app.teardown_request
def teardown_request(exception):
    if hasattr(g, 'db'):
        g.db.close()


@app.route('/')
def index():
    cursor = g.db.cursor()
    cursor.execute('SELECT article, created_date FROM articles ORDER BY created_date DESC')
    return render_template('index.html', var={'articles': cursor.fetchall(), \
                                              'title': os.getenv('TITLE') + ' - top',
                                              })


@app.route('/write', methods=['GET', 'POST'])
def write():
    var = {'article': '', 'date': '', 'title': os.getenv('TITLE')}
    if 'POST' == request.method and session['login']:
        var['date'] = request.form['date']
        try:
            cursor = g.db.cursor()
            cursor.execute('INSERT INTO articles (article, created_date) VALUES (%s, %s)', \
                               [request.form['text'], var['date']])
        except:
            g.db.rollback()
            cursor = g.db.cursor()
            cursor.execute('UPDATE articles SET article = %s WHERE created_date = %s', \
                               [request.form['text'], var['date']])

        g.db.commit()

    else:
        var['date'] = request.args.get('date')

    if ('' == var['date'] or None == var['date']):
        var['date'] = '%4d%02d%02d' % (g.today.year, g.today.month, g.today.day)

    try:
        cursor = g.db.cursor()
        cursor.execute('SELECT article FROM articles WHERE created_date = %s', [var['date']])
        var['article'] = cursor.fetchone()[0]
    except:
        var['article'] = ''

    return render_template('write.html', var=var)


@app.route('/article')
def article():
    cursor = g.db.cursor()
    sql = 'SELECT article, created_date ' + \
          'FROM articles ' + \
          'WHERE created_date >= (SELECT COALESCE((SELECT created_date FROM articles WHERE created_date < %s ORDER BY created_date DESC LIMIT 1), 1)) ' + \
          'ORDER BY created_date ASC ' + \
          'LIMIT 3'
    cursor.execute(sql, [request.args.get('date')])
    prev = current = next = None
    articles = cursor.fetchall()
    for article in articles:
        if article[1] < int(request.args.get('date')):
            if None == prev:
                prev = {'article': markdown.markdown(article[0].decode('utf-8')), 'date': article[1]}
        elif article[1] == int(request.args.get('date')):
            if None == current:
                current = {'article': markdown.markdown(article[0].decode('utf-8')), 'date': article[1]}
        else:
            if None == next:
                next = {'article': markdown.markdown(article[0].decode('utf-8')), 'date': article[1]}

    return render_template('article.html', var={'prev': prev, \
                                                'current': current,\
                                                'next': next, \
                                                'title': os.getenv('TITLE') + ' - ' + date_filter(request.args.get('date')), \
                                                'date': request.args.get('date'),
                                                })


@app.route('/search')
def search():
    q = request.args.get('q')
    cursor = g.db.cursor()
    cursor.execute('SELECT article, created_date FROM articles WHERE article ILIKE %(like)s ORDER BY created_date DESC', \
                       dict(like='%'+q+'%'))
    return render_template('search.html', var={'articles': cursor.fetchall(), \
                                               'title': os.getenv('TITLE') + ' - search', \
                                               'q': q,
                                               })


@app.route('/api', methods=['POST'])
def api():
    if session['login']:
        return markdown.markdown(request.form['article'])


@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'POST' == request.method:
        if os.getenv('PASSWORD') == request.form['pass']:
            session['login'] = True
            return redirect(url_for('index'))

    return render_template('login.html', var={'title': os.getenv('TITLE') + ' - login'})


@app.route('/logout')
def logout():
    session.pop('login', None)
    return redirect(url_for('index'))


@app.route('/rss')
def rss():
    rss = '<?xml version="1.0" encoding="UTF-8"?>' + "\n" + \
          '<rss version="2.0">' + "\n" + \
          '<channel>' + "\n" + \
          '<title>' + os.getenv('TITLE').decode('utf-8') + '</title>' + "\n" + \
          '<link>' + '%s://%s/' % (request.scheme.decode('utf-8'), request.host.decode('utf-8')) + '</link>' + "\n" + \
          '<description>' + os.getenv('TITLE').decode('utf-8') + '</description>' + "\n" + \
          '<language>ja</language>' + "\n"

    cursor = g.db.cursor()
    cursor.execute('SELECT article, created_date FROM articles ORDER BY created_date DESC LIMIT 20')
    articles = cursor.fetchall()

    for article in articles:
        t = datetime.date(int(str(article[1])[0:4]), int(str(article[1])[4:6]), int(str(article[1])[6:8]))
        rss += '<item>' + "\n" + \
              '<title>' + date_filter(article[1]) + '</title>' + "\n" + \
              '<link>' + '%s://%s/article?date=%s' % (request.scheme, request.host, article[1]) + '</link>' + "\n" + \
              '<description>' + "\n" + \
              '<![CDATA[' + "\n" + markdown.markdown(article[0].decode('utf-8')) + "\n" + \
              ']]>' + "\n" + \
              '</description>' + "\n" + \
              '<pubDate>' + t.isoformat() + '</pubDate>' + "\n" + \
              '</item>' + "\n"

    rss += '</channel>' + "\n" + \
           '</rss>'

    response = app.make_response(rss)
    response.headers['Content-Type'] = 'application/rss+xml'
    return response


@app.errorhandler(404)
def http_error_404(error):
    # FIXME
    return "404: not found."


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0',
            port=port,
            # ssl_context=(None if (bool(os.getenv('DEBUG'))) else 'adhoc'))
            )
