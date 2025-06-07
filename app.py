from email import charset
import mimetypes
import re
from flask import Flask, request, render_template, jsonify, send_file
import os
from urllib.parse import unquote
import datetime
from werkzeug.utils import secure_filename
import math
from pathlib import Path
import platform
import io
import uuid
from supabase import create_client, Client
import tempfile

app = Flask(__name__)

# Cấu hình Supabase
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
SUPABASE_BUCKET = os.environ.get('SUPABASE_BUCKET', 'uploads')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Vui lòng cấu hình SUPABASE_URL và SUPABASE_KEY trong environment variables")

# Khởi tạo Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def secure_folder_name(filename):
    """Làm sạch tên thư mục nhưng giữ lại dấu tiếng Việt"""
    if not filename:
        return ""
    
    # Chỉ loại bỏ các ký tự thực sự nguy hiểm
    # Giữ lại chữ cái có dấu, số, khoảng trắng, gạch ngang, gạch dưới
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)  # Loại bỏ ký tự không an toàn cho tên file/folder
    filename = re.sub(r'\.\.+', '.', filename)  # Loại bỏ nhiều dấu chấm liên tiếp
    filename = filename.strip('. ')  # Loại bỏ dấu chấm và khoảng trắng ở đầu/cuối
    
    # Thay thế nhiều khoảng trắng bằng một khoảng trắng
    filename = re.sub(r'\s+', ' ', filename)
    
    return filename

# Cấu hình app
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# In thông tin Supabase khi khởi động
print(f"=== FILE UPLOAD SERVER WITH SUPABASE ===")
print(f"Supabase URL: {SUPABASE_URL}")
print(f"Supabase Bucket: {SUPABASE_BUCKET}")
print("Files will be stored in Supabase Storage")
print("=" * 50)

def init_db():
    """Khởi tạo bảng submissions trong Supabase"""
    try:
        # Tạo bảng submissions nếu chưa có
        # Lưu ý: Bạn cần tạo bảng này trong Supabase Dashboard hoặc SQL Editor
        result = supabase.table('submissions').select('*').limit(1).execute()
        print("Database connection successful!")
    except Exception as e:
        print(f"Database initialization error: {str(e)}")
        print("Vui lòng tạo bảng 'submissions' trong Supabase với schema sau:")
        print("""
        CREATE TABLE submissions (
            id SERIAL PRIMARY KEY,
            ho_ten TEXT NOT NULL,
            noi_cong_tac TEXT,
            khoa_phong TEXT,
            ten_de_tai TEXT NOT NULL,
            gio_quy_doi REAL DEFAULT 0,
            minh_chung TEXT,
            ghi_chu TEXT,
            file_name TEXT,
            file_url TEXT,
            file_size INTEGER DEFAULT 0,
            folder_name TEXT,
            upload_time TIMESTAMP DEFAULT NOW(),
            upload_ip TEXT,
            storage_path TEXT
        );
        """)

init_db()

ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'xls', 'xlsx', 'zip', 'rar', '7z'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def format_file_size(size_bytes):
    """Chuyển đổi byte sang định dạng dễ đọc"""
    if size_bytes is None:
        return "0 B"
    
    try:
        if isinstance(size_bytes, str):
            size_bytes = int(size_bytes) if size_bytes.isdigit() else 0
        size_bytes = int(size_bytes)
    except (ValueError, TypeError):
        return "0 B"
    
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_names[i]}"

def get_client_ip():
    """Lấy IP client"""
    if request.environ.get('HTTP_X_FORWARDED_FOR') is None:
        return request.environ['REMOTE_ADDR']
    else:
        return request.environ['HTTP_X_FORWARDED_FOR']

def upload_to_supabase(file, folder_name=None):
    """Upload file lên Supabase Storage"""
    try:
        # Tạo tên file unique
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_id = str(uuid.uuid4())[:8]
        original_name = secure_filename(file.filename)
        name, ext = os.path.splitext(original_name)
        file_name = f"{name}_{timestamp}_{unique_id}{ext}"
        
        # Xác định đường dẫn trong bucket
        if folder_name:
            storage_path = f"{folder_name}/{file_name}"
        else:
            storage_path = file_name
        
        # Đọc file content
        file_content = file.read()
        file_size = len(file_content)
        
        # Upload lên Supabase Storage
        result = supabase.storage.from_(SUPABASE_BUCKET).upload(
            path=storage_path,
            file=file_content,
            file_options={
                "content-type": file.content_type or "application/octet-stream"
            }
        )
        
        if result.status_code == 200:
            # Lấy public URL
            public_url = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(storage_path)
            
            return {
                'success': True,
                'file_name': file_name,
                'storage_path': storage_path,
                'file_url': public_url,
                'file_size': file_size
            }
        else:
            return {
                'success': False,
                'error': f"Upload failed: {result.status_code}"
            }
            
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/info')
def server_info():
    """API để lấy thông tin server"""
    return jsonify({
        'storage_type': 'Supabase Storage',
        'supabase_url': SUPABASE_URL,
        'supabase_bucket': SUPABASE_BUCKET,
        'server_platform': platform.system(),
        'allowed_extensions': list(ALLOWED_EXTENSIONS),
        'max_file_size': app.config['MAX_CONTENT_LENGTH'],
        'max_file_size_human': format_file_size(app.config['MAX_CONTENT_LENGTH'])
    })

@app.route('/upload', methods=['POST'])
def upload_file():
    try:
        # Lấy IP client
        client_ip = get_client_ip()
        
        # Lấy dữ liệu form
        ho_ten = request.form.get('ho_ten', '').strip()
        ten_de_tai = request.form.get('ten_de_tai', '').strip()
        noi_cong_tac = request.form.get('noi_cong_tac', '').strip()
        khoa_phong = request.form.get('khoa_phong', '').strip()
        gio_quy_doi = request.form.get('gio_quy_doi', '0')
        minh_chung = request.form.get('minh_chung', '').strip()
        ghi_chu = request.form.get('ghi_chu', '').strip()
        folder_name = request.form.get('folder', '').strip()

        # Chỉ kiểm tra họ tên và tên đề tài
        if not all([ho_ten, ten_de_tai]):
            return jsonify({'error': 'Vui lòng điền đầy đủ họ tên và tên đề tài'}), 400

        try:
            gio_quy_doi = float(gio_quy_doi)
        except ValueError:
            gio_quy_doi = 0.0

        file_url = None
        file_name = None
        file_size = 0
        storage_path = None
        final_folder_name = None

        # Xử lý folder name
        if folder_name:
            safe_folder_name = secure_folder_name(folder_name)
            if not safe_folder_name:
                return jsonify({'error': 'Tên thư mục không hợp lệ'}), 400
            final_folder_name = safe_folder_name

        # Xử lý file upload
        if 'file' in request.files:
            file = request.files['file']
            if file and hasattr(file, 'filename') and file.filename and file.filename.strip():
                if allowed_file(file.filename):
                    # Upload lên Supabase
                    upload_result = upload_to_supabase(file, final_folder_name)
                    
                    if upload_result['success']:
                        file_name = upload_result['file_name']
                        file_url = upload_result['file_url']
                        file_size = upload_result['file_size']
                        storage_path = upload_result['storage_path']
                        
                        print(f"File uploaded to Supabase: {storage_path} ({format_file_size(file_size)}) from IP: {client_ip}")
                    else:
                        return jsonify({'error': f'Lỗi upload: {upload_result["error"]}'}), 500
                else:
                    return jsonify({'error': 'Loại file không được hỗ trợ'}), 400

        # Lưu vào Supabase Database
        try:
            result = supabase.table('submissions').insert({
                'ho_ten': ho_ten,
                'ten_de_tai': ten_de_tai,
                'noi_cong_tac': noi_cong_tac,
                'khoa_phong': khoa_phong,
                'gio_quy_doi': gio_quy_doi,
                'minh_chung': minh_chung,
                'ghi_chu': ghi_chu,
                'file_name': file_name,
                'file_url': file_url,
                'file_size': file_size,
                'folder_name': final_folder_name,
                'upload_time': datetime.datetime.now().isoformat(),
                'upload_ip': client_ip,
                'storage_path': storage_path
            }).execute()
            
            print(f"Data saved to Supabase database: {result}")
            
        except Exception as e:
            print(f"Database error: {str(e)}")
            # Nếu lưu DB lỗi nhưng file đã upload, có thể cần xóa file
            return jsonify({'error': f'Lỗi lưu database: {str(e)}'}), 500

        # Tạo message phản hồi
        if final_folder_name:
            message = f'Đã upload thành công vào thư mục "{final_folder_name}" trên Supabase'
        else:
            message = 'Upload thành công lên Supabase Storage!'
        
        if file_url:
            message += f' - URL: {file_url}'

        return jsonify({
            'message': message,
            'file_name': file_name,
            'file_url': file_url,
            'file_size': file_size,
            'file_size_human': format_file_size(file_size),
            'folder': final_folder_name,
            'storage_path': storage_path,
            'client_ip': client_ip
        })

    except Exception as e:
        print(f"Upload error: {str(e)}")
        return jsonify({'error': f'Lỗi: {str(e)}'}), 500

@app.route('/submissions')
def list_submissions():
    """API để lấy danh sách submissions"""
    try:
        result = supabase.table('submissions').select('*').order('upload_time', desc=True).execute()
        return jsonify({
            'submissions': result.data,
            'count': len(result.data)
        })
    except Exception as e:
        return jsonify({'error': f'Lỗi lấy dữ liệu: {str(e)}'}), 500

@app.route('/download/<int:submission_id>')
def download_file(submission_id):
    """Download file từ Supabase Storage"""
    try:
        # Lấy thông tin file từ database
        result = supabase.table('submissions').select('*').eq('id', submission_id).single().execute()
        
        if not result.data:
            return jsonify({'error': 'Không tìm thấy file'}), 404
        
        submission = result.data
        storage_path = submission.get('storage_path')
        file_name = submission.get('file_name')
        
        if not storage_path:
            return jsonify({'error': 'File không có trên storage'}), 404
        
        # Download file từ Supabase Storage
        file_response = supabase.storage.from_(SUPABASE_BUCKET).download(storage_path)
        
        if file_response:
            # Trả về file
            return send_file(
                io.BytesIO(file_response),
                as_attachment=True,
                download_name=file_name,
                mimetype='application/octet-stream'
            )
        else:
            return jsonify({'error': 'Không thể download file'}), 500
            
    except Exception as e:
        return jsonify({'error': f'Lỗi download: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))