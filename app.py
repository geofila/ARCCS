from flask import Flask, render_template, request, jsonify, Response
import os
import json
import queue
import threading
from werkzeug.utils import secure_filename
import openai

# Set OpenAI API key
openai.api_key = os.getenv("OPENAI_API_KEY", "")
# Import RPEM and CCM modules
from RPEM import (
    load_pdf_document,
    elements_to_markdown,
    split_into_sections,
    process_all_sections,
    collect_all_regulations,
    filter_regulations_by_quality,
)
from CCM import (
    check_regulation_compliance,
    check_all_regulations,
    generate_compliance_report
)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32MB max file size

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Allowed file extensions
ALLOWED_EXTENSIONS = {'pdf', 'txt', 'json'}

# Default AI model to use
DEFAULT_MODEL = "gpt-5.2"

# Global message queue for SSE streaming
log_queues = {}

def get_log_queue(session_id='default'):
    """Get or create a log queue for a session"""
    if session_id not in log_queues:
        log_queues[session_id] = queue.Queue()
    return log_queues[session_id]

def send_log(message, log_type='info', session_id='default'):
    """Send a log message to the frontend via SSE"""
    q = get_log_queue(session_id)
    q.put({'type': log_type, 'message': message})
    # Also print to console
    print(message)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Global state to store processed data between requests
app_state = {
    'regulation_file': None,
    'proposal_file': None,
    'extracted_regulations': [],
    'proposal_text': None
}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/stream-logs')
def stream_logs():
    """SSE endpoint to stream logs to the frontend"""
    def generate():
        q = get_log_queue('default')
        while True:
            try:
                # Wait for a message with timeout
                msg = q.get(timeout=30)
                data = json.dumps(msg)
                yield f"data: {data}\n\n"
            except queue.Empty:
                # Send keepalive
                yield f"data: {json.dumps({'type': 'keepalive', 'message': ''})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream',
                   headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

@app.route('/upload-regulation', methods=['POST'])
def upload_regulation():
    """Handle regulation/compliance document upload"""
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No file selected'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'success': False, 'message': 'File type not allowed. Use PDF, TXT, or JSON.'}), 400
    
    # Save file
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'regulation_' + filename)
    file.save(filepath)
    
    app_state['regulation_file'] = filepath
    
    return jsonify({
        'success': True,
        'message': 'Regulation document uploaded successfully',
        'filename': file.filename
    })

@app.route('/process-regulation', methods=['POST'])
def process_regulation():
    """Process the regulation document using RPEM and extract features"""
    try:
        filepath = app_state.get('regulation_file')
        
        if not filepath or not os.path.exists(filepath):
            return jsonify({'success': False, 'message': 'No regulation file found. Please upload first.'}), 400
        
        file_ext = filepath.rsplit('.', 1)[1].lower()
        
        if file_ext == 'pdf':
            # Use RPEM to process PDF
            send_log("=" * 60)
            send_log(f"🔍 RPEM: Processing PDF: {os.path.basename(filepath)}")
            send_log("=" * 60)
            
            # Load and parse PDF
            send_log("📄 Loading PDF document...")
            elements = load_pdf_document(filepath, strategy="fast")
            markdown_text = elements_to_markdown(elements)
            sections = split_into_sections(markdown_text)
            
            send_log(f"📑 Split into {len(sections)} sections", 'success')
            
            # Extract regulations from sections using AI
            send_log(f"🤖 Extracting regulations with AI (model: {DEFAULT_MODEL})...")
            send_log("⏳ This may take several minutes for large documents...", 'warning')
            
            # Process sections one by one with logging
            analysis_results = []
            for i, section in enumerate(sections):
                section_title = section.get('title', 'Untitled')[:40]
                send_log(f"📝 [{i+1}/{len(sections)}] Processing: {section_title}...")
                
                # Process single section using extract_regulations_from_section
                from RPEM import extract_regulations_from_section
                result = extract_regulations_from_section(section, model=DEFAULT_MODEL)
                analysis_results.append(result)
                
                if result.get('contains_regulation'):
                    regs_count = len(result.get('regulations', []))
                    send_log(f"   ✅ Found {regs_count} regulation(s)", 'success')
            
            # Collect all regulations
            all_regulations = collect_all_regulations(analysis_results)
            
            send_log(f"📋 Total regulations extracted: {len(all_regulations)}", 'info')
            
            if len(all_regulations) == 0:
                # If no regulations found, check for errors
                errors = [r.get('error') for r in analysis_results if r.get('error')]
                if errors:
                    send_log(f"⚠️ Errors encountered: {errors[0]}", 'error')
                    return jsonify({
                        'success': False,
                        'message': f'Processing error: {errors[0] if errors else "Unknown error"}'
                    }), 500
            
            # Filter by quality
            send_log("🔍 Filtering by quality...")
            filtered = filter_regulations_by_quality(all_regulations, min_score=40, verbose=False)
            
            # Keep regulations that passed filtering
            kept_regulations = filtered["kept"] + filtered["review"]
            app_state['extracted_regulations'] = kept_regulations
            
            # Collect unique domains and keywords
            domains = set()
            keywords = set()
            for reg in kept_regulations:
                if reg.get('domain') and isinstance(reg['domain'], dict):
                    primary = reg['domain'].get('primary_domain')
                    if primary:
                        domains.add(primary)
                if reg.get('keywords'):
                    keywords.update(reg['keywords'][:10])
            
            send_log("")
            send_log("✅ Processing complete!", 'success')
            send_log(f"   Regulations kept: {len(kept_regulations)}")
            send_log(f"   Domains: {list(domains)[:5]}")
            
            return jsonify({
                'success': True,
                'message': 'Processing complete',
                'features': {
                    'total_regulations': len(kept_regulations),
                    'categories': list(domains)[:10],
                    'keywords': list(keywords)[:20],
                    'sections_analyzed': len(sections),
                    'sections_with_regulations': sum(1 for r in analysis_results if r.get("contains_regulation"))
                }
            })
            
        elif file_ext == 'json':
            # Load regulations from JSON file
            send_log(f"📄 Loading regulations from JSON: {os.path.basename(filepath)}")
            
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Handle different JSON structures (from extracted_regulations.json or direct list)
            if isinstance(data, list):
                regulations = data
            elif isinstance(data, dict):
                # Try different common keys used in RPEM output
                if 'regulations' in data:
                    regulations = data['regulations']
                elif 'filtered_regulations' in data:
                    regulations = data['filtered_regulations']
                elif 'all_regulations' in data:
                    regulations = data['all_regulations']
                elif 'kept' in data:
                    regulations = data['kept']
                else:
                    # Maybe it's a single regulation object
                    regulations = [data]
            else:
                regulations = [data]
            
            send_log(f"✅ Loaded {len(regulations)} regulations from JSON", 'success')
            
            app_state['extracted_regulations'] = regulations
            
            # Collect domains and keywords
            domains = set()
            keywords = set()
            for reg in regulations:
                if reg.get('domain') and isinstance(reg['domain'], dict):
                    primary = reg['domain'].get('primary_domain')
                    if primary:
                        domains.add(primary)
                if reg.get('keywords'):
                    keywords.update(reg['keywords'][:10])
            
            send_log(f"   Domains found: {list(domains)[:5]}")
            
            return jsonify({
                'success': True,
                'message': f'Loaded {len(regulations)} regulations from JSON',
                'features': {
                    'total_regulations': len(regulations),
                    'categories': list(domains)[:10],
                    'keywords': list(keywords)[:20],
                    'sections_analyzed': 1,
                    'sections_with_regulations': 1
                }
            })
            
        elif file_ext == 'txt':
            # For TXT files, treat as a single section
            print(f"\n📄 Processing TXT file as regulation document: {filepath}")
            
            with open(filepath, 'r', encoding='utf-8') as f:
                text_content = f.read()
            
            print(f"   Content length: {len(text_content)} characters")
            
            sections = [{'title': '## Document Content', 'content': text_content}]
            analysis_results = process_all_sections(sections, model=DEFAULT_MODEL, verbose=True)
            all_regulations = collect_all_regulations(analysis_results)
            
            filtered = filter_regulations_by_quality(all_regulations, min_score=40, verbose=True)
            kept_regulations = filtered["kept"] + filtered["review"]
            app_state['extracted_regulations'] = kept_regulations
            
            domains = set()
            keywords = set()
            for reg in kept_regulations:
                if reg.get('domain') and isinstance(reg['domain'], dict):
                    primary = reg['domain'].get('primary_domain')
                    if primary:
                        domains.add(primary)
                if reg.get('keywords'):
                    keywords.update(reg['keywords'][:10])
            
            return jsonify({
                'success': True,
                'message': 'Processing complete',
                'features': {
                    'total_regulations': len(kept_regulations),
                    'categories': list(domains)[:10],
                    'keywords': list(keywords)[:20],
                    'sections_analyzed': 1,
                    'sections_with_regulations': len([r for r in analysis_results if r.get("contains_regulation")])
                }
            })
        
        return jsonify({'success': False, 'message': 'Unsupported file format'}), 400
        
    except Exception as e:
        print(f"❌ Error processing regulation: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'Error processing document: {str(e)}'
        }), 500

@app.route('/upload-proposal', methods=['POST'])
def upload_proposal():
    """Handle proposal document upload"""
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No file selected'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'success': False, 'message': 'File type not allowed. Use PDF, TXT, or JSON.'}), 400
    
    # Save file
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'proposal_' + filename)
    file.save(filepath)
    
    app_state['proposal_file'] = filepath
    
    return jsonify({
        'success': True,
        'message': 'Proposal document uploaded successfully',
        'filename': file.filename
    })

@app.route('/process-proposal', methods=['POST'])
def process_proposal():
    """Process the proposal document - extract text for compliance checking"""
    try:
        filepath = app_state.get('proposal_file')
        
        if not filepath or not os.path.exists(filepath):
            return jsonify({'success': False, 'message': 'No proposal file found. Please upload first.'}), 400
        
        file_ext = filepath.rsplit('.', 1)[1].lower()
        
        if file_ext == 'pdf':
            # Use RPEM to extract text from PDF
            elements = load_pdf_document(filepath, strategy="fast")
            proposal_text = elements_to_markdown(elements)
        elif file_ext == 'txt':
            with open(filepath, 'r', encoding='utf-8') as f:
                proposal_text = f.read()
        elif file_ext == 'json':
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            proposal_text = json.dumps(data, indent=2, ensure_ascii=False)
        else:
            return jsonify({'success': False, 'message': 'Unsupported file format'}), 400
        
        app_state['proposal_text'] = proposal_text
        
        # Calculate some basic stats
        lines = proposal_text.split('\n')
        sections = [l for l in lines if l.startswith('#')]
        words = len(proposal_text.split())
        
        # Estimate complexity based on length
        if words < 1000:
            complexity = 'Low'
        elif words < 5000:
            complexity = 'Medium'
        else:
            complexity = 'High'
        
        return jsonify({
            'success': True,
            'message': 'Proposal processed successfully',
            'data': {
                'sections': len(sections) if sections else max(1, len(lines) // 50),
                'pages': max(1, words // 300),
                'complexity': complexity,
                'word_count': words
            }
        })
        
    except Exception as e:
        print(f"❌ Error processing proposal: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'Error processing proposal: {str(e)}'
        }), 500

@app.route('/run-compliance-check', methods=['POST'])
def run_compliance_check():
    """Run compliance checking between regulation and proposal using CCM with live streaming"""
    try:
        regulations = app_state.get('extracted_regulations', [])
        proposal_text = app_state.get('proposal_text')
        
        if not regulations:
            return jsonify({
                'success': False,
                'message': 'No regulations found. Please process a regulation document first.'
            }), 400
        
        if not proposal_text:
            return jsonify({
                'success': False,
                'message': 'No proposal text found. Please process a proposal document first.'
            }), 400
        
        send_log("=" * 60)
        send_log("🔍 CCM: COMPLIANCE CLASSIFICATION")
        send_log("=" * 60)
        send_log(f"   Regulations to check: {len(regulations)}")
        send_log(f"   Proposal length: {len(proposal_text):,} characters")
        send_log(f"   Model: {DEFAULT_MODEL}")
        send_log("=" * 60)
        
        # Limit regulations to check (for performance)
        max_regulations = 10
        regulations_to_check = regulations[:max_regulations]
        
        if len(regulations) > max_regulations:
            send_log(f"⚠️ Limiting to first {max_regulations} regulations (total: {len(regulations)})", 'warning')
        
        # Check each regulation individually with streaming
        results = []
        for i, reg in enumerate(regulations_to_check):
            reg_name = reg.get('regulation_name') or 'Unknown'
            reg_name = reg_name[:55] if reg_name else 'Unknown'
            send_log(f"⚖️ [{i+1}/{len(regulations_to_check)}] Checking: {reg_name}...")
            
            result = check_regulation_compliance(
                regulation=reg,
                proposal_chunk=proposal_text,
                model=DEFAULT_MODEL
            )
            
            status = result.get('compliance_status', 'UNKNOWN')
            
            if status == 'NON_COMPLIANT':
                send_log(f"   ❌ NON_COMPLIANT - Contradiction found!", 'error')
                if result.get('contradiction_details'):
                    send_log(f"      → {result['contradiction_details'][:80]}...", 'error')
            else:
                send_log(f"   ✅ COMPLIANT", 'success')
            
            results.append(result)
        
        # Generate report
        report = generate_compliance_report(results)
        
        send_log("")
        send_log("✅ Compliance check complete!")
        send_log(f"   Compliant: {report['summary']['compliant']}")
        send_log(f"   Non-Compliant: {report['summary']['non_compliant']}")
        send_log(f"   Insufficient Info: {report['summary'].get('insufficient_info', 0)}")
        send_log(f"   Human Required: {report['summary'].get('human_required', 0)}")
        
        # Convert to frontend format
        frontend_results = []
        for r in results:
            status = r.get('compliance_status', 'UNKNOWN')
            
            if status == 'COMPLIANT':
                frontend_status = 'pass'
            elif status == 'NON_COMPLIANT':
                frontend_status = 'fail'
            elif status == 'INSUFFICIENT_INFORMATION':
                frontend_status = 'info'
            elif status == 'HUMAN_REQUIRED':
                frontend_status = 'warning'
            else:
                frontend_status = 'warning'
            
            # Get full explanation for modal, truncated for preview
            full_explanation = r.get('contradiction_details', '') or r.get('missing_information', '') or r.get('explanation', 'No details available')
            preview_message = full_explanation[:200] + '...' if len(full_explanation) > 200 else full_explanation
            
            frontend_results.append({
                'regulation': r.get('regulation_name', 'Unknown Regulation'),
                'regulation_id': r.get('regulation_id', 'N/A'),
                'status': frontend_status,
                'compliance_status': status,  # Keep original status for modal
                'message': preview_message,
                'missing_information': r.get('missing_information', ''),
                'explanation': r.get('explanation', 'No explanation available'),
                'contradiction_details': r.get('contradiction_details', ''),
                'evidence': r.get('evidence', ''),
                'confidence': r.get('confidence_score', 0),
                'domain': r.get('domain', {}),
                'regulation_text': r.get('regulation_text', ''),
                'keywords': r.get('keywords', []),
                'obligations': r.get('obligations', []),
                'source_section': r.get('source_section', ''),
                'raw_data': r  # Include all raw data
            })
        
        summary = report['summary']
        
        return jsonify({
            'success': True,
            'message': 'Compliance check completed',
            'results': frontend_results,
            'summary': {
                'total': summary['total'],
                'passed': summary['compliant'],
                'failed': summary['non_compliant'],
                'insufficient_info': summary.get('insufficient_info', 0),
                'human_required': summary.get('human_required', 0),
                'warnings': summary.get('insufficient_info', 0) + summary.get('human_required', 0),
                'compliance_rate': summary['compliance_rate']
            },
            'overall_status': report['overall_status']
        })
        
    except Exception as e:
        print(f"❌ Error during compliance check: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'Error during compliance check: {str(e)}'
        }), 500

@app.route('/export-report', methods=['GET'])
def export_report():
    """Export the compliance report as JSON"""
    try:
        regulations = app_state.get('extracted_regulations', [])
        proposal_text = app_state.get('proposal_text')
        
        if not regulations or not proposal_text:
            return jsonify({
                'success': False,
                'message': 'No compliance check has been run yet.'
            }), 400
        
        # Re-run compliance check to get fresh results
        results = check_all_regulations(
            regulations=regulations,
            proposal_chunk=proposal_text,
            model="gpt-5.2",
            verbose=False
        )
        
        report = generate_compliance_report(results)
        
        return jsonify({
            'success': True,
            'report': report
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error exporting report: {str(e)}'
        }), 500

@app.route('/load-saved-regulations', methods=['POST'])
def load_saved_regulations():
    """Load pre-extracted regulations from deduplicated_regulations.json"""
    try:
        # Use deduplicated_regulations.json as the primary source
        json_path = os.path.join(os.path.dirname(__file__), 'deduplicated_regulations.json')
        
        if not os.path.exists(json_path):
            # Fallback to extracted_regulations.json if deduplicated doesn't exist
            json_path = os.path.join(os.path.dirname(__file__), 'extracted_regulations.json')
            
        if not os.path.exists(json_path):
            return jsonify({
                'success': False,
                'message': 'No regulations file found. Please process a regulation document first.'
            }), 404
        
        send_log(f"📄 Loading regulations from: {os.path.basename(json_path)}")
        
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Handle different JSON structures
        if isinstance(data, list):
            regulations = data
        elif isinstance(data, dict):
            # Try common keys from different outputs
            regulations = (data.get('cleaned_regulations') or 
                          data.get('regulations') or 
                          data.get('filtered_regulations') or 
                          data.get('all_regulations') or 
                          [])
        else:
            regulations = []
        
        app_state['extracted_regulations'] = regulations
        
        # Collect domains and keywords
        domains = set()
        keywords = set()
        for reg in regulations:
            if reg.get('domain') and isinstance(reg['domain'], dict):
                primary = reg['domain'].get('primary_domain')
                if primary:
                    domains.add(primary)
            if reg.get('keywords'):
                keywords.update(reg['keywords'][:10])
        
        send_log(f"✅ Loaded {len(regulations)} pre-extracted GDPR regulations", 'success')
        send_log(f"   Domains: {list(domains)[:5]}")
        
        return jsonify({
            'success': True,
            'message': f'Loaded {len(regulations)} GDPR regulations',
            'features': {
                'total_regulations': len(regulations),
                'categories': list(domains)[:10],
                'keywords': list(keywords)[:20]
            }
        })
        
    except Exception as e:
        print(f"❌ Error loading saved regulations: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'Error loading regulations: {str(e)}'
        }), 500

@app.route('/reset', methods=['POST'])
def reset_state():
    """Reset the application state"""
    global app_state
    app_state = {
        'regulation_file': None,
        'proposal_file': None,
        'extracted_regulations': [],
        'proposal_text': None
    }
    return jsonify({'success': True, 'message': 'State reset successfully'})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
