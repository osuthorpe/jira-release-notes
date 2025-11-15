#!/usr/bin/env python3
"""
Improved Web interface for JIRA Release Notes Generator with real-time progress
"""

import os
import logging
import uuid
import threading
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename
from automated_release_notes import AutomatedReleaseNotes
import tempfile
import shutil

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your-secret-key-change-this')

# Initialize SocketIO for real-time communication
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Configure upload settings
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'csv'}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB limit

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# Ensure upload directory exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Job tracking
active_jobs = {}

class JobStatus:
    def __init__(self, job_id):
        self.job_id = job_id
        self.status = 'starting'
        self.progress = 0
        self.message = 'Initializing...'
        self.result = None
        self.error = None
        self.created_at = datetime.now()

def allowed_file(filename):
    """Check if the uploaded file has an allowed extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def process_file_background(job_id, csv_file_path, room_id):
    """Background task to process the CSV file and generate release notes."""
    job = active_jobs[job_id]
    
    def progress_callback(message, progress=None):
        """Callback to update progress via WebSocket."""
        job.message = message
        if progress is not None:
            job.progress = progress
        logger.info(f"Job {job_id}: {message}")
        socketio.emit('progress_update', {
            'job_id': job_id,
            'status': job.status,
            'progress': job.progress,
            'message': message
        }, room=room_id)
    
    try:
        progress_callback("Initializing release notes generator...", 5)
        generator = AutomatedReleaseNotes()
        
        progress_callback("Reading CSV file...", 10)
        issues = generator.read_csv_issues(csv_file_path)
        
        if not issues:
            job.status = 'error'
            job.error = 'No issues found in the CSV file'
            progress_callback("Error: No issues found in CSV file", 0)
            return
        
        progress_callback(f"Found {len(issues)} issues. Starting AI processing...", 15)
        
        # Custom progress callback that updates WebSocket
        def ai_progress_callback(message):
            # Extract progress if it's in the message
            if "Progress:" in message and "%" in message:
                try:
                    progress_str = message.split("Progress:")[1].split("%")[0].strip()
                    progress_val = int(progress_str)
                    progress_callback(message, 15 + int(progress_val * 0.7))  # Scale to 15-85%
                except:
                    progress_callback(message)
            else:
                progress_callback(message)
        
        # Generate release notes HTML with progress tracking
        job.status = 'processing'
        release_notes_html = generator.generate_release_notes_html(issues, ai_progress_callback)
        
        progress_callback("Saving release notes file...", 90)
        
        # Create article title
        day_of_week, formatted_date = generator.format_date()
        article_title = f"Product Release Notes - {formatted_date}"
        
        # Save release notes locally
        output_file_path = generator.save_release_notes_locally(article_title, release_notes_html)
        
        # Store result
        job.status = 'completed'
        job.progress = 100
        job.result = {
            'filename': os.path.basename(output_file_path),
            'title': article_title,
            'issue_count': len(issues),
            'file_path': output_file_path
        }
        
        progress_callback(f"✅ Complete! Generated release notes for {len(issues)} issues.", 100)
        
        # Send completion event
        socketio.emit('job_complete', {
            'job_id': job_id,
            'result': job.result
        }, room=room_id)
        
    except Exception as e:
        job.status = 'error'
        job.error = str(e)
        logger.error(f"Error in background job {job_id}: {e}")
        progress_callback(f"❌ Error: {str(e)}", 0)
        
        socketio.emit('job_error', {
            'job_id': job_id,
            'error': str(e)
        }, room=room_id)
    
    finally:
        # Clean up uploaded file
        if os.path.exists(csv_file_path):
            os.remove(csv_file_path)

@app.route('/')
def index():
    """Main upload page."""
    return render_template('index_improved.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle file upload and start background processing."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file selected'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not (file and allowed_file(file.filename)):
        return jsonify({'error': 'Invalid file type. Please upload a CSV file.'}), 400
    
    try:
        # Generate unique job ID
        job_id = str(uuid.uuid4())
        
        # Save uploaded file
        filename = secure_filename(file.filename)
        temp_csv_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_id}_{filename}")
        file.save(temp_csv_path)
        
        # Create job status
        active_jobs[job_id] = JobStatus(job_id)
        
        # Start background processing
        room_id = f"job_{job_id}"
        thread = threading.Thread(
            target=process_file_background,
            args=(job_id, temp_csv_path, room_id)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'job_id': job_id,
            'message': 'File uploaded successfully. Processing started.'
        })
        
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        return jsonify({'error': f'Error uploading file: {str(e)}'}), 500

@app.route('/job/<job_id>')
def job_status(job_id):
    """Get job status."""
    if job_id not in active_jobs:
        return jsonify({'error': 'Job not found'}), 404
    
    job = active_jobs[job_id]
    return jsonify({
        'job_id': job_id,
        'status': job.status,
        'progress': job.progress,
        'message': job.message,
        'result': job.result,
        'error': job.error,
        'created_at': job.created_at.isoformat()
    })

@app.route('/download/<filename>')
def download_file(filename):
    """Download generated release notes file."""
    try:
        # Security check: ensure filename is safe
        filename = secure_filename(filename)
        file_path = os.path.join('output', filename)
        
        if not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404
        
        return send_file(file_path, as_attachment=True)
        
    except Exception as e:
        logger.error(f"Error downloading file: {e}")
        return jsonify({'error': 'Error downloading file'}), 500

@app.route('/copy-content/<filename>')
def get_copy_content(filename):
    """Get the HTML content for copy-paste into Zendesk."""
    try:
        # Security check: ensure filename is safe
        filename = secure_filename(filename)
        file_path = os.path.join('output', filename)
        
        if not os.path.exists(file_path):
            return 'File not found', 404
        
        # Read the HTML file and extract the content for Zendesk
        with open(file_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        # Extract the body content between the main content divs
        # Look for the content that starts after the header and before the footer
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Find the main content area - look for release notes content
        content_div = soup.find('div', class_='content') or soup.find('body')
        
        if content_div:
            # Clean up the HTML for Zendesk while preserving structure
            zendesk_html = clean_html_for_zendesk(content_div)
            return zendesk_html, 200, {'Content-Type': 'text/html; charset=utf-8'}
        else:
            return 'Could not extract content', 404
        
    except Exception as e:
        logger.error(f"Error getting copy content: {e}")
        return f'Error loading content: {str(e)}', 500

def clean_html_for_zendesk(content_div):
    """Clean HTML content for Zendesk while preserving structure."""
    from bs4 import BeautifulSoup
    
    # Create a copy to avoid modifying the original
    cleaned_soup = BeautifulSoup(str(content_div), 'html.parser')
    
    # Remove unwanted elements
    for element in cleaned_soup.find_all(['script', 'style', 'meta', 'link']):
        element.decompose()
    
    # Remove specific classes and IDs that might cause issues
    for element in cleaned_soup.find_all():
        if element.name:
            # Remove CSS classes but keep basic structure
            if 'class' in element.attrs:
                del element.attrs['class']
            if 'id' in element.attrs:
                del element.attrs['id']
            if 'style' in element.attrs:
                del element.attrs['style']
    
    # Convert divs with specific roles to appropriate semantic elements
    for div in cleaned_soup.find_all('div'):
        # If div contains only text and formatting, convert to p
        if not div.find_all(['div', 'section', 'article', 'header', 'footer', 'nav']):
            if div.get_text().strip():
                div.name = 'p'
    
    # Ensure we have clean HTML structure
    html_content = str(cleaned_soup)
    
    # Remove extra whitespace while preserving structure
    lines = html_content.split('\n')
    cleaned_lines = [line.strip() for line in lines if line.strip()]
    
    return '\n'.join(cleaned_lines)

@app.route('/api/status')
def api_status():
    """API endpoint to check if the service is running."""
    return jsonify({
        'status': 'running',
        'service': 'JIRA Release Notes Generator',
        'version': '2.0',
        'features': ['WebSocket support', 'Background processing', 'Real-time progress']
    })

# WebSocket events
@socketio.on('connect')
def on_connect():
    logger.info(f"Client connected: {request.sid}")
    emit('connected', {'message': 'Connected to server'})

@socketio.on('disconnect')
def on_disconnect():
    logger.info(f"Client disconnected: {request.sid}")

@socketio.on('join_job')
def on_join_job(data):
    """Join a job room to receive updates."""
    job_id = data.get('job_id')
    if job_id:
        room = f"job_{job_id}"
        join_room(room)
        logger.info(f"Client {request.sid} joined job room {room}")
        emit('joined_job', {'job_id': job_id, 'room': room})

@socketio.on('leave_job')
def on_leave_job(data):
    """Leave a job room."""
    job_id = data.get('job_id')
    if job_id:
        room = f"job_{job_id}"
        leave_room(room)
        logger.info(f"Client {request.sid} left job room {room}")
        emit('left_job', {'job_id': job_id, 'room': room})

@app.errorhandler(413)
def too_large(e):
    """Handle file too large error."""
    return jsonify({'error': 'File is too large. Maximum size is 16MB.'}), 413

# Cleanup old jobs periodically
def cleanup_old_jobs():
    """Remove jobs older than 1 hour."""
    import threading
    import time
    
    def cleanup():
        while True:
            try:
                current_time = datetime.now()
                jobs_to_remove = []
                
                for job_id, job in active_jobs.items():
                    if (current_time - job.created_at).seconds > 3600:  # 1 hour
                        jobs_to_remove.append(job_id)
                
                for job_id in jobs_to_remove:
                    del active_jobs[job_id]
                    logger.info(f"Cleaned up old job: {job_id}")
                
                time.sleep(300)  # Check every 5 minutes
                
            except Exception as e:
                logger.error(f"Error in cleanup thread: {e}")
                time.sleep(60)
    
    cleanup_thread = threading.Thread(target=cleanup)
    cleanup_thread.daemon = True
    cleanup_thread.start()

if __name__ == '__main__':
    # Create output directory if it doesn't exist
    os.makedirs('output', exist_ok=True)
    
    # Start cleanup thread
    cleanup_old_jobs()
    
    # Try different ports
    ports = [8080, 8000, 3000, 5001, 8888]
    
    for port in ports:
        try:
            print(f"🚀 Starting improved server on port {port}...")
            print(f"🌟 Features: WebSocket support, Background processing, Real-time progress")
            socketio.run(app, debug=True, host='127.0.0.1', port=port, use_reloader=False, allow_unsafe_werkzeug=True)
            break
        except OSError as e:
            print(f"Port {port} is busy, trying next port...")
            continue
    else:
        print("Could not find an available port. Please check for running processes.")