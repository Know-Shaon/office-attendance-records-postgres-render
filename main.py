from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, session
import psycopg2
import pandas as pd
import os
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.styles import Font, Protection

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# Database connection
conn = psycopg2.connect(
    host="dpg-cq9f9k2ju9rs73b53rag-a.oregon-postgres.render.com",
    database="ford_office_attendance_records",
    user="ford_office_attendance_records_user",
    password="gLmdxUmTPA1JAgcDKOfBS9PIez0ugggt",
    port="5432"
)
cursor = conn.cursor()

# Ensure the Attendance Records directory exists
if not os.path.exists('Attendance Records'):
    os.makedirs('Attendance Records')

# Create tables if they don't exist
cursor.execute('''
CREATE TABLE IF NOT EXISTS teams (
    team_id TEXT PRIMARY KEY,
    team_name TEXT,
    password TEXT
)
''')
cursor.execute('''
CREATE TABLE IF NOT EXISTS members (
    member_id SERIAL PRIMARY KEY,
    team_id TEXT,
    member_name TEXT,
    FOREIGN KEY(team_id) REFERENCES teams(team_id)
)
''')
cursor.execute('''
CREATE TABLE IF NOT EXISTS attendance (
    id SERIAL PRIMARY KEY,
    member_id INTEGER,
    date TEXT,
    status TEXT,
    FOREIGN KEY(member_id) REFERENCES members(member_id)
)
''')
conn.commit()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
    team_id = request.form['team_id'].upper()
    password = request.form['password']
    cursor.execute('SELECT password FROM teams WHERE team_id = %s', (team_id,))
    record = cursor.fetchone()
    if record and record[0] == password:
        session['team_id'] = team_id
        return redirect(url_for('add_member', team_id=team_id))
    else:
        flash('Invalid credentials')
        return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.pop('team_id', None)
    return redirect(url_for('index'))

@app.route('/create_team', methods=['GET', 'POST'])
def create_team():
    if request.method == 'POST':
        team_name = request.form['team_name'].upper()
        password = request.form['password']
        cursor.execute('SELECT team_id FROM teams WHERE team_id = %s', (team_name,))
        existing_team = cursor.fetchone()
        if existing_team:
            flash('Team ID already exists')
        else:
            cursor.execute('''
            INSERT INTO teams (team_id, team_name, password) VALUES (%s, %s, %s)
            ''', (team_name, team_name, password))
            conn.commit()
            flash('Team created successfully')
        return redirect(url_for('index'))
    return render_template('create_team.html')

@app.route('/add_member/<team_id>', methods=['GET', 'POST'])
def add_member(team_id):
    team_id = team_id.upper()
    if request.method == 'POST':
        member_name = request.form['member_name']
        cursor.execute('SELECT member_id FROM members WHERE team_id = %s AND member_name = %s', (team_id, member_name))
        existing_member = cursor.fetchone()
        if existing_member:
            flash('Member already exists')
        else:
            cursor.execute('''
            INSERT INTO members (team_id, member_name) VALUES (%s, %s)
            ''', (team_id, member_name))
            conn.commit()
            flash('Member added successfully')
    cursor.execute('SELECT member_name FROM members WHERE team_id = %s', (team_id,))
    members = cursor.fetchall()
    return render_template('add_member.html', team_id=team_id, members=members)

@app.route('/mark_attendance/<team_id>/<member_name>', methods=['GET', 'POST'])
def mark_attendance(team_id, member_name):
    team_id = team_id.upper()
    if request.method == 'POST':
        date = request.form['date']
        status = request.form['status']
        cursor.execute('SELECT member_id FROM members WHERE team_id = %s AND member_name = %s', (team_id, member_name))
        member_id = cursor.fetchone()
        if member_id:
            cursor.execute('''
            INSERT INTO attendance (member_id, date, status) VALUES (%s, %s, %s)
            ''', (member_id[0], date, status))
            conn.commit()
            try:
                update_excel(team_id)
                flash('Attendance marked successfully')
            except PermissionError:
                flash('Attendance marked, but unable to update Excel file. Please close the file if it is open.')
        else:
            flash('Member not found')
        return redirect(url_for('logout'))  # Log out after marking attendance
    return render_template('mark_attendance.html', team_id=team_id, member_name=member_name)

@app.route('/export_data')
def export_data():
    cursor.execute('SELECT * FROM attendance')
    records = cursor.fetchall()
    df = pd.DataFrame(records, columns=['ID', 'Member ID', 'Date', 'Status'])
    df.to_csv('attendance_records.csv', index=False)
    flash('Data exported to CSV successfully')
    return redirect(url_for('index'))

@app.route('/download/<filename>')
def download_file(filename):
    return send_from_directory('Attendance Records', filename)

@app.route('/track_attendance/<team_id>', methods=['GET', 'POST'])
def track_attendance(team_id):
    team_id = team_id.upper()
    if request.method == 'POST':
        member_name = request.form['member_name']
        cursor.execute('''
        SELECT status, COUNT(*) FROM attendance
        JOIN members ON attendance.member_id = members.member_id
        WHERE members.team_id = %s AND members.member_name = %s
        GROUP BY status
        ''', (team_id, member_name))
        records = cursor.fetchall()
        stats = {status: count for status, count in records}
        return render_template('attendance_stats.html', team_id=team_id, member_name=member_name, stats=stats)
    cursor.execute('SELECT member_name FROM members WHERE team_id = %s', (team_id,))
    members = cursor.fetchall()
    return render_template('track_attendance.html', team_id=team_id, members=members)

@app.route('/download_monthly_report/<team_id>', methods=['GET', 'POST'])
def download_monthly_report(team_id):
    team_id = team_id.upper()
    if request.method == 'POST':
        month = request.form['month']
        year = request.form['year']
        cursor.execute('''
        SELECT t.team_name, m.member_name, a.date, a.status
        FROM attendance a
        JOIN members m ON a.member_id = m.member_id
        JOIN teams t ON m.team_id = t.team_id
        WHERE t.team_id = %s AND a.date LIKE %s
        ''', (team_id, f'{year}-{month}%'))
        records = cursor.fetchall()
        df = pd.DataFrame(records, columns=['Team Name', 'Member Name', 'Date', 'Status'])

        filename = f'{team_id}_attendance_{year}_{month}.xlsx'
        wb = Workbook()
        ws = wb.active
        ws.title = "Attendance Records"

        for r in dataframe_to_rows(df, index=False, header=True):
            ws.append(r)

        for col in ws.columns:
            max_length = 0
            column = col[0].column_letter
            for cell in col:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(cell.value)
                except:
                    pass
            adjusted_width = (max_length + 2)
            ws.column_dimensions[column].width = adjusted_width

        for row in ws.iter_rows(min_row=1, min_col=1, max_row=1, max_col=len(df.columns)):
            for cell in row:
                cell.protection = Protection(locked=True)
                cell.font = Font(bold=True)

        ws.protection.sheet = True
        wb.save(os.path.join('Attendance Records', filename))

        return send_from_directory('Attendance Records', filename)

    return render_template('download_monthly_report.html', team_id=team_id)

@app.route('/admin_login')
def admin_login():
    return render_template('admin_login.html')

@app.route('/admin', methods=['POST'])
def admin():
    admin_password = request.form['admin_password']
    if admin_password == 'Admin@123':
        return render_template('admin.html')
    else:
        flash('Invalid admin password')
        return redirect(url_for('admin_login'))

@app.route('/remove_team', methods=['POST'])
def remove_team():
    team_id = request.form['team_id'].upper()
    cursor.execute('DELETE FROM attendance WHERE member_id IN (SELECT member_id FROM members WHERE team_id = %s)', (team_id,))
    cursor.execute('DELETE FROM members WHERE team_id = %s', (team_id,))
    cursor.execute('DELETE FROM teams WHERE team_id = %s', (team_id,))
    conn.commit()
    flash('Team and all its members and attendance records removed successfully')
    return redirect(url_for('admin'))

@app.route('/remove_member', methods=['POST'])
def remove_member():
    team_id = request.form['team_id'].upper()
    member_name = request.form['member_name']
    cursor.execute('SELECT member_id FROM members WHERE team_id = %s AND member_name = %s', (team_id, member_name))
    member_id = cursor.fetchone()
    if member_id:
        cursor.execute('DELETE FROM attendance WHERE member_id = %s', (member_id,))
        cursor.execute('DELETE FROM members WHERE member_id = %s', (member_id,))
        conn.commit()
        flash('Member and all their attendance records removed successfully')
    else:
        flash('Member not found')
    return redirect(url_for('admin'))

def update_excel(team_id):
    cursor.execute('''
    SELECT t.team_name, m.member_name, a.date, a.status
    FROM attendance a
    JOIN members m ON a.member_id = m.member_id
    JOIN teams t ON m.team_id = t.team_id
    WHERE t.team_id = %s
    ''', (team_id,))
    records = cursor.fetchall()
    df = pd.DataFrame(records, columns=['Team Name', 'Member Name', 'Date', 'Status'])

    wb = Workbook()
    ws = wb.active
    ws.title = "Attendance Records"

    for r in dataframe_to_rows(df, index=False, header=True):
        ws.append(r)

    for col in ws.columns:
        max_length = 0
        column = col[0].column_letter
        for cell in col:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(cell.value)
            except:
                pass
        adjusted_width = (max_length + 2)
        ws.column_dimensions[column].width = adjusted_width

    for row in ws.iter_rows(min_row=1, min_col=1, max_row=1, max_col=len(df.columns)):
        for cell in row:
            cell.protection = Protection(locked=True)
            cell.font = Font(bold=True)

    ws.protection.sheet = True
    filename = f'{team_id}_attendance_records.xlsx'
    wb.save(os.path.join('Attendance Records', filename))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
