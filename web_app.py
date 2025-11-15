#!/usr/bin/env python3
"""
Web interface for JIRA Release Notes Generator
"""

import os
import logging
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from werkzeug.utils import secure_filename
from automated_release_notes import AutomatedReleaseNotes
import tempfile
import shutil

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your-secret-key-change-this')

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


def allowed_file(filename):
    """Check if the uploaded file has an allowed extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/')
def index():
    """Main upload page."""
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle file upload and process release notes."""
    if 'file' not in request.files:
        flash('No file selected')
        return redirect(request.url)
    
    file = request.files['file']
    
    if file.filename == '':
        flash('No file selected')
        return redirect(request.url)
    
    if file and allowed_file(file.filename):
        try:
            # Save uploaded file
            filename = secure_filename(file.filename)
            temp_csv_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(temp_csv_path)
            
            # Initialize release notes generator
            generator = AutomatedReleaseNotes()
            
            # Process the uploaded CSV file
            issues = generator.read_csv_issues(temp_csv_path)
            
            if not issues:
                flash('No issues found in the CSV file')
                os.remove(temp_csv_path)  # Clean up
                return redirect(url_for('index'))
            
            # Generate release notes HTML
            release_notes_html = generator.generate_release_notes_html(issues)
            
            # Create article title
            day_of_week, formatted_date = generator.format_date()
            article_title = f"Product Release Notes - {formatted_date}"
            
            # Save release notes locally
            output_file_path = generator.save_release_notes_locally(article_title, release_notes_html)
            
            # Clean up uploaded file
            os.remove(temp_csv_path)
            
            # Get just the filename for the download link
            output_filename = os.path.basename(output_file_path)
            
            flash(f'Release notes generated successfully! {len(issues)} issues processed.')
            return render_template('success.html', 
                                 filename=output_filename, 
                                 title=article_title,
                                 issue_count=len(issues))
            
        except Exception as e:
            logger.error(f"Error processing file: {e}")
            flash(f'Error processing file: {str(e)}')
            # Clean up on error
            if os.path.exists(temp_csv_path):
                os.remove(temp_csv_path)
            return redirect(url_for('index'))
    else:
        flash('Invalid file type. Please upload a CSV file.')
        return redirect(url_for('index'))


@app.route('/download/<filename>')
def download_file(filename):
    """Download generated release notes file."""
    try:
        # Security check: ensure filename is safe
        filename = secure_filename(filename)
        file_path = os.path.join('output', filename)
        
        if not os.path.exists(file_path):
            flash('File not found')
            return redirect(url_for('index'))
        
        return send_file(file_path, as_attachment=True)
        
    except Exception as e:
        logger.error(f"Error downloading file: {e}")
        flash('Error downloading file')
        return redirect(url_for('index'))


@app.route('/api/status')
def api_status():
    """API endpoint to check if the service is running."""
    return jsonify({
        'status': 'running',
        'service': 'JIRA Release Notes Generator',
        'version': '1.0'
    })


@app.errorhandler(413)
def too_large(e):
    """Handle file too large error."""
    flash('File is too large. Maximum size is 16MB.')
    return redirect(url_for('index'))


if __name__ == '__main__':
    # Create output directory if it doesn't exist
    os.makedirs('output', exist_ok=True)
    
    # Try different ports
    ports = [8080, 8000, 3000, 5001, 8888]
    
    for port in ports:
        try:
            print(f"Trying to start server on port {port}...")
            app.run(debug=True, host='127.0.0.1', port=port, use_reloader=False)
            break
        except OSError as e:
            print(f"Port {port} is busy, trying next port...")
            continue
    else:
        print("Could not find an available port. Please check for running processes.")