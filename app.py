# Thêm các import cần thiết ở đầu file
import hashlib
import json
import logging
import tempfile
import re  # Thêm import re cho hàm secure_folder_name
from typing import Optional
from flask import Flask, request, render_template, jsonify, send_file, abort
import os
from urllib.parse import unquote
from datetime import datetime
# Sử dụng: datetime.now()
import pytz
from werkzeug.utils import secure_filename
import math
from pathlib import Path
import platform
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import os

import uuid
from supabase import create_client, Client  
import zipfile
import shutil
from pathlib import Path

from utils import format_file_size, secure_folder_name
# Cấu hình logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
# Cấu hình Supabase với giá trị mặc định và kiểm tra tốt hơn
SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')
SUPABASE_BUCKET = os.environ.get('SUPABASE_BUCKET', 'file-uploads')


# Kiểm tra và hướng dẫn cấu hình
if not SUPABASE_URL or not SUPABASE_KEY:
    print("=" * 60)
    print("❌ CẢNH BÁO: Thiếu cấu hình Supabase!")
    print("=" * 60)
    print("Vui lòng cấu hình các biến môi trường sau:")
    print("")
    print("🔧 CÁCH 1: Sử dụng file .env")
    print("Tạo file .env trong thư mục gốc với nội dung:")
    print("SUPABASE_URL=https://your-project-ref.supabase.co")
    print("SUPABASE_KEY=your-anon-public-key")
    print("SUPABASE_BUCKET=file-uploads")
    print("")
    print("🔧 CÁCH 2: Set biến môi trường (Windows)")
    print("set SUPABASE_URL=https://your-project-ref.supabase.co")
    print("set SUPABASE_KEY=your-anon-public-key")
    print("set SUPABASE_BUCKET=file-uploads")
    print("")
    print("🔧 CÁCH 3: Set biến môi trường (Linux/Mac)")
    print("export SUPABASE_URL=https://your-project-ref.supabase.co")
    print("export SUPABASE_KEY=your-anon-public-key")
    print("export SUPABASE_BUCKET=file-uploads")
    print("")
    print("📋 Lấy thông tin Supabase:")
    print("1. Đăng nhập vào https://supabase.com")
    print("2. Chọn project của bạn")
    print("3. Vào Settings > API")
    print("4. Copy URL và anon/public key")
    print("")
    print("=" * 60)
    
    # Cho phép chạy ở chế độ demo (không kết nối Supabase)
    print("🚀 Khởi động ở chế độ DEMO (không có Supabase)")
    print("Ứng dụng sẽ chạy nhưng không thể upload file thật")
    print("=" * 60)
    
    # Tạo mock supabase client để tránh lỗi
    class MockSupabase:
        def __init__(self):
            self.storage_instance = MockStorage()
            self.table_instance = MockTable()
        
        def storage(self):
            return self.storage_instance
        
        def table(self, table_name):
            return self.table_instance
    
    class MockStorage:
        def from_(self, bucket):
            return MockBucket()
    
    class MockBucket:
        def upload(self, path, file, file_options=None):
            return MockResult(200)
        
        def get_public_url(self, path):
            return f"https://demo.example.com/{path}"
        
        def list(self, path=""):
            return []
        
        def download(self, path):
            return b"Demo file content"
    
    class MockTable:
        def insert(self, data):
            return MockResult(200, data)
        
        def select(self, fields="*"):
            return self
        
        def eq(self, field, value):
            return self
        
        def single(self):
            return self
        
        def limit(self, count):
            return self
        
        def order(self, field, desc=False):
            return self
        
        def execute(self):
            return MockResult(200, [])
    
    class MockResult:
        def __init__(self, status_code, data=None):
            self.status_code = status_code
            self.data = data or []
    
    supabase = MockSupabase()
    DEMO_MODE = True
else:
    # Khởi tạo Supabase client thật
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        DEMO_MODE = False
        print(f"✅ Kết nối Supabase thành công!")
        print(f"📍 URL: {SUPABASE_URL}")
        print(f"🗂️ Bucket: {SUPABASE_BUCKET}")
    except Exception as e:
        print(f"❌ Lỗi kết nối Supabase: {str(e)}")
        print("🔄 Chuyển sang chế độ DEMO")
        # Sử dụng mock client
        DEMO_MODE = True
# Cache để tránh gọi API nhiều lần



# Cấu hình app
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# In thông tin khởi động
print(f"=== FILE UPLOAD SERVER ===")
if DEMO_MODE:
    print("⚠️  CHẠY Ở CHẾ ĐỘ DEMO")
    print("📝 Chức năng upload sẽ mô phỏng")
else:
    print("✅ CHẠY VỚI SUPABASE")
    print(f"🌐 Supabase URL: {SUPABASE_URL}")
    print(f"🗂️ Bucket: {SUPABASE_BUCKET}")
print("=" * 30)

def init_db():
    """Khởi tạo bảng submissions trong Supabase"""
    if DEMO_MODE:
        print("📝 Demo mode: Bỏ qua kiểm tra database")
        return
    
    try:
        # Tạo bảng submissions nếu chưa có
        result = supabase.table('submissions').select('*').limit(1).execute()
        print("✅ Database connection successful!")
    except Exception as e:
        print(f"❌ Database initialization error: {str(e)}")
        print("📋 Vui lòng tạo bảng 'submissions' trong Supabase với schema sau:")
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

def secure_filename_vietnamese(filename):
    """
    Chuyển đổi tên file thành format an toàn, hỗ trợ tiếng Việt
    """
    if not filename:
        return filename
    
    # Tách tên file và extension
    name, ext = os.path.splitext(filename)
    
    # Sử dụng hàm secure_folder_name để xử lý phần tên
    safe_name = secure_folder_name(name)
    
    if not safe_name:
        # Fallback nếu không xử lý được
        safe_name = secure_filename(name)
    
    return f"{safe_name}{ext}"

def get_client_ip():
    """Lấy IP client"""
    if request.environ.get('HTTP_X_FORWARDED_FOR') is None:
        return request.environ['REMOTE_ADDR']
    else:
        return request.environ['HTTP_X_FORWARDED_FOR']

def calculate_file_checksum(file_path: Path) -> Optional[str]:
    """Tính MD5 checksum của file"""
    try:
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception:
        return None




def upload_to_supabase(file, folder_name=None):
    """Upload file lên Supabase Storage - Enhanced version with better error handling"""
    
    if DEMO_MODE:
        # Mô phỏng upload thành công
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_id = str(uuid.uuid4())[:8]
        original_name = secure_filename_vietnamese(file.filename)
        name, ext = os.path.splitext(original_name)
        file_name = f"{name}_{timestamp}_{unique_id}{ext}"
        
        if folder_name:
            storage_path = f"{folder_name}/{file_name}"
        else:
            storage_path = file_name
        
        return {
            'success': True,
            'file_name': file_name,
            'storage_path': storage_path,
            'file_url': f"https://demo.example.com/{storage_path}",
            'file_size': 1024
        }
    
    try:
        # Tạo tên file unique
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_id = str(uuid.uuid4())[:8]
        original_name = secure_filename_vietnamese(file.filename)
        name, ext = os.path.splitext(original_name)
        file_name = f"{name}_{timestamp}_{unique_id}{ext}"
        
        # Xác định đường dẫn trong bucket
        if folder_name:
            storage_path = f"{folder_name}/{file_name}"
        else:
            storage_path = file_name
        
        # Đọc file content
        file.seek(0)  # Reset file pointer
        file_content = file.read()
        file_size = len(file_content)
        
        if file_size == 0:
            return {
                'success': False,
                'error': "File is empty"
            }
        
        # Kiểm tra kết nối Supabase
        if not supabase:
            return {
                'success': False,
                'error': "Supabase client not initialized"
            }
        
        # Upload lên Supabase Storage - Enhanced version
        try:
            # Reset file pointer again before upload
            file.seek(0)
            
            # Attempt upload with different approaches
            storage_client = supabase.storage.from_(SUPABASE_BUCKET)
            
            # Method 1: Direct upload with file object
            try:
                result = storage_client.upload(
                    path=storage_path,
                    file=file_content,
                    file_options={
                        "content-type": file.content_type or "application/octet-stream",
                        "upsert": "false"  # Prevent overwrite
                    }
                )
                
                # Debug: Log the result structure
                logging.debug(f"Upload result type: {type(result)}")
                logging.debug(f"Upload result: {result}")
                
                # Enhanced response parsing
                success = False
                error_msg = None
                
                # Case 1: New supabase-py version (dict response)
                if isinstance(result, dict):
                    if result.get('error'):
                        error_msg = str(result['error'])
                    elif result.get('data') or 'path' in result:
                        success = True
                    else:
                        error_msg = "Unknown dict response format"
                
                # Case 2: Object with attributes
                elif hasattr(result, 'data') and hasattr(result, 'error'):
                    if result.error:
                        error_msg = str(result.error)
                    elif result.data:
                        success = True
                    else:
                        error_msg = "No data in response"
                
                # Case 3: Direct success (some versions return path directly)
                elif isinstance(result, str):
                    success = True
                
                # Case 4: Other object types
                else:
                    # Try to convert to dict
                    try:
                        result_dict = result.__dict__ if hasattr(result, '__dict__') else {}
                        if result_dict.get('data') or result_dict.get('path'):
                            success = True
                        else:
                            error_msg = f"Unknown response object: {type(result)}"
                    except:
                        error_msg = f"Cannot parse response type: {type(result)}"
                
                if success:
                    # Get public URL
                    try:
                        public_url_result = storage_client.get_public_url(storage_path)
                        
                        # Handle different URL response formats
                        if isinstance(public_url_result, str):
                            file_url = public_url_result
                        elif isinstance(public_url_result, dict):
                            file_url = public_url_result.get('publicUrl') or public_url_result.get('url')
                        elif hasattr(public_url_result, 'publicUrl'):
                            file_url = public_url_result.publicUrl
                        else:
                            file_url = f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{storage_path}"
                        
                        return {
                            'success': True,
                            'file_name': file_name,
                            'storage_path': storage_path,
                            'file_url': file_url,
                            'file_size': file_size
                        }
                    except Exception as url_error:
                        # Upload succeeded but URL generation failed
                        fallback_url = f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{storage_path}"
                        return {
                            'success': True,
                            'file_name': file_name,
                            'storage_path': storage_path,
                            'file_url': fallback_url,
                            'file_size': file_size,
                            'warning': f"URL generation warning: {str(url_error)}"
                        }
                else:
                    return {
                        'success': False,
                        'error': f"Upload failed: {error_msg or 'Unknown error'}"
                    }
                    
            except Exception as upload_error:
                error_str = str(upload_error)
                
                # Handle specific Supabase errors
                if "already exists" in error_str.lower():
                    return {
                        'success': False,
                        'error': "File already exists. Please try again."
                    }
                elif "permission" in error_str.lower():
                    return {
                        'success': False,
                        'error': "Permission denied. Check bucket policies."
                    }
                elif "size" in error_str.lower():
                    return {
                        'success': False,
                        'error': f"File size error: {error_str}"
                    }
                else:
                    return {
                        'success': False,
                        'error': f"Upload exception: {error_str}"
                    }
                    
        except Exception as storage_error:
            return {
                'success': False,
                'error': f"Storage client error: {str(storage_error)}"
            }
            
    except Exception as e:
        return {
            'success': False,
            'error': f"General error: {str(e)}"
        }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/info')
def server_info():
    """API để lấy thông tin server"""
    storage_info = "Demo Mode (No Supabase)" if DEMO_MODE else "Supabase Storage"
    
    return jsonify({
        'storage_type': storage_info,
        'demo_mode': DEMO_MODE,
        'supabase_url': SUPABASE_URL if not DEMO_MODE else "Not configured",
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
                    # Upload lên Supabase (hoặc mô phỏng)
                    upload_result = upload_to_supabase(file, final_folder_name)
                    
                    if upload_result['success']:
                        file_name = upload_result['file_name']
                        file_url = upload_result['file_url']
                        file_size = upload_result['file_size']
                        storage_path = upload_result['storage_path']
                        
                        status_text = "Demo upload" if DEMO_MODE else "Uploaded to Supabase"
                        print(f"{status_text}: {storage_path} ({format_file_size(file_size)}) from IP: {client_ip}")
                    else:
                        return jsonify({'error': f'Lỗi upload: {upload_result["error"]}'}), 500
                else:
                    return jsonify({'error': 'Loại file không được hỗ trợ'}), 400

        # Lưu vào database (hoặc mô phỏng)
        try:
            submission_data = {
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
                'upload_time': datetime.now().isoformat(),
                'upload_ip': client_ip,
                'storage_path': storage_path
            }
            
            if not DEMO_MODE:
                result = supabase.table('submissions').insert(submission_data).execute()
                print(f"Data saved to Supabase database: {result}")
            else:
                print(f"Demo mode - would save: {submission_data}")
            
        except Exception as e:
            print(f"Database error: {str(e)}")
            if not DEMO_MODE:
                return jsonify({'error': f'Lỗi lưu database: {str(e)}'}), 500

        # Tạo message phản hồi
        if DEMO_MODE:
            message = "Demo upload thành công! (Không có Supabase thật)"
        else:
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
            'client_ip': client_ip,
            'demo_mode': DEMO_MODE
        })

    except Exception as e:
        print(f"Upload error: {str(e)}")
        return jsonify({'error': f'Lỗi: {str(e)}'}), 500

def list_files_only_recursive(bucket_name, folder_path=""):
    """
    Chỉ lấy danh sách FILE, KHÔNG bao gồm folder
    Được thiết kế đặc biệt để tránh xóa nhầm folder
    """
    if DEMO_MODE:
        return []
    
    try:
        files_only = []
        
        # Lấy danh sách items trong folder hiện tại
        result = supabase.storage.from_(bucket_name).list(folder_path)
        
        if not result:
            return files_only
            
        for item in result:
            item_name = item.get('name', '')
            if not item_name:
                continue
                
            # Tạo full path
            if folder_path:
                full_path = f"{folder_path}/{item_name}"
            else:   
                full_path = item_name
            
            # LOGIC CHẶT CHẼ để chỉ lấy FILE
            item_id = item.get('id')
            item_size = item.get('size')
            item_mimetype = item.get('mimetype') 
            
            # File phải có ít nhất 1 trong các đặc điểm này:
            # 1. Có ID (Supabase tự generate cho file)
            # 2. Có size > 0 
            # 3. Có mimetype
            # 4. Có extension rõ ràng
            has_clear_extension = (
                '.' in item_name and 
                not item_name.startswith('.') and
                len(item_name.split('.')[-1]) <= 10  # Extension hợp lệ
            )
            
            is_definitely_file = (
                (item_id is not None) or 
                (item_size is not None and item_size > 0) or 
                (item_mimetype is not None and item_mimetype.strip() != '') or
                has_clear_extension
            )
            
            # QUAN TRỌNG: Chỉ xử lý nếu chắc chắn là FILE
            if is_definitely_file:
                files_only.append({
                    'name': item_name,
                    'path': full_path,
                    'type': 'file',
                    'size': item_size or 0,
                    'mimetype': item_mimetype or '',
                    'last_modified': item.get('updated_at', item.get('created_at', '')),
                    'metadata': item
                })
                logger.debug(f"✓ Detected FILE: {full_path} (size: {item_size}, mimetype: {item_mimetype})")
            else:
                # Đây có thể là folder - Đệ quy để tìm file bên trong
                # NHƯNG KHÔNG thêm folder vào danh sách
                logger.debug(f"📁 Detected FOLDER: {full_path} - exploring inside...")
                try:
                    subfolder_files = list_files_only_recursive(bucket_name, full_path)
                    files_only.extend(subfolder_files)
                except Exception as subfolder_error:
                    logger.warning(f"Cannot explore subfolder {full_path}: {str(subfolder_error)}")
        
        return files_only
        
    except Exception as e:
        logger.error(f"Error listing files in {folder_path}: {str(e)}")
        return []

def delete_only_files_safe(bucket_name, file_items, batch_size=5):
    """
    An toàn chỉ xóa FILE, tuyệt đối không xóa folder
    """
    if DEMO_MODE:
        return {'deleted': len(file_items), 'failed': 0, 'errors': []}
    
    deleted_count = 0
    failed_count = 0
    errors = []
    
    logger.info(f"🎯 Starting SAFE file deletion for {len(file_items)} files...")
    
    # Xử lý từng file một cách cẩn thận
    for i, file_item in enumerate(file_items):
        file_path = file_item['path']
        file_name = file_item['name']
        
        try:
            # KIỂM TRA CUỐI CÙNG: Đây có phải file không?
            if not file_name or '.' not in file_name:
                logger.warning(f"⚠️ SKIP suspicious path (no extension): {file_path}")
                continue
                
            # Kiểm tra extension hợp lệ
            extension = file_name.split('.')[-1].lower()
            valid_extensions = [
                'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg',  # Images
                'pdf', 'doc', 'docx', 'txt', 'rtf',  # Documents  
                'xls', 'xlsx', 'csv',  # Spreadsheets
                'mp4', 'avi', 'mov', 'wmv', 'flv',  # Videos
                'mp3', 'wav', 'flac', 'aac',  # Audio
                'zip', 'rar', '7z', 'tar', 'gz',  # Archives
                'json', 'xml', 'html', 'css', 'js', 'py', 'java', 'cpp'  # Code
            ]
            
            if extension not in valid_extensions:
                logger.warning(f"⚠️ SKIP unknown extension: {file_path} (.{extension})")
                continue
            
            logger.info(f"🗑️ Deleting file [{i+1}/{len(file_items)}]: {file_path}")
            
            # Thực hiện xóa file
            result = supabase.storage.from_(bucket_name).remove([file_path])
            
            if result:
                deleted_count += 1
                logger.info(f"✅ Successfully deleted: {file_path}")
            else:
                deleted_count += 1  # Coi như thành công nếu không có error
                logger.info(f"✅ File processed (may already be deleted): {file_path}")
                
        except Exception as file_error:
            error_str = str(file_error).lower()
            if any(keyword in error_str for keyword in ['not found', 'does not exist', 'not exist']):
                deleted_count += 1
                logger.info(f"✅ File already deleted: {file_path}")
            else:
                failed_count += 1
                error_msg = f"❌ Failed to delete {file_path}: {str(file_error)}"
                errors.append(error_msg)
                logger.error(error_msg)
        
        # Delay để tránh rate limit
        if (i + 1) % batch_size == 0 and (i + 1) < len(file_items):
            time.sleep(1)
            logger.info(f"⏳ Processed {i + 1}/{len(file_items)} files...")
    
    return {
        'deleted': deleted_count,
        'failed': failed_count,
        'errors': errors
    }

@app.route('/api/storage/cleanup-files-only', methods=['POST'])
def cleanup_files_only():
    """API để CHỈ XÓA FILE - TUYỆT ĐỐI KHÔNG XÓA THƯ MỤC"""
    try:
        if DEMO_MODE:
            return jsonify({
                'success': True,
                'message': '🔧 Demo mode: Mô phỏng xóa files (thư mục được bảo vệ)',
                'demo_mode': True,
                'total_files': 0,
                'deleted': 0,
                'failed': 0,
                'errors': []
            })
        
        client_ip = get_client_ip()
        logger.warning(f"🛡️ SAFE FILES-ONLY CLEANUP initiated from IP: {client_ip}")
        
        # Sử dụng hàm mới chỉ lấy file
        logger.info("📋 Scanning for FILES ONLY (folders are protected)...")
        file_items = list_files_only_recursive(SUPABASE_BUCKET)
        
        if not file_items:
            return jsonify({
                'success': True,
                'message': '✅ Không tìm thấy file nào để xóa (thư mục được bảo vệ)',
                'total_files': 0,
                'deleted': 0,
                'failed': 0,
                'errors': []
            })
        
        total_files = len(file_items)
        total_size = sum(item.get('size', 0) for item in file_items)
        
        logger.info(f"📊 Found {total_files} FILES to delete")
        logger.info(f"📦 Total size: {format_file_size(total_size)}")
        logger.info(f"🛡️ ALL FOLDERS WILL BE PROTECTED")
        
        # Log một vài file đầu để kiểm tra
        logger.info("📋 Sample files to delete:")
        for i, item in enumerate(file_items[:5]):
            logger.info(f"  {i+1}. {item['path']} ({format_file_size(item.get('size', 0))})")
        if len(file_items) > 5:
            logger.info(f"  ... and {len(file_items) - 5} more files")
        
        # Thực hiện xóa AN TOÀN
        logger.info("🚀 Starting PROTECTED file deletion...")
        delete_result = delete_only_files_safe(SUPABASE_BUCKET, file_items)
        
        # Xóa database records (optional)
        db_deleted = 0
        try:
            db_result = supabase.table('submissions').delete().neq('id', 0).execute()
            db_deleted = len(db_result.data) if db_result.data else 0
            logger.info(f"🗄️ Cleaned {db_deleted} database records")
        except Exception as e:
            logger.warning(f"⚠️ Database cleanup failed: {str(e)}")
        
        # Kết quả
        success_rate = (delete_result['deleted'] / total_files * 100) if total_files > 0 else 100
        
        message = f"🛡️ ĐÃ XÓA {delete_result['deleted']}/{total_files} FILE - THƯ MỤC ĐƯỢC BẢO VỆ"
        if delete_result['failed'] > 0:
            message += f" (❌ {delete_result['failed']} lỗi)"
        if db_deleted > 0:
            message += f" (🗄️ DB: {db_deleted} records)"
        
        logger.warning(f"🛡️ PROTECTED CLEANUP COMPLETED: {message}")
        
        return jsonify({
            'success': True,
            'message': message,
            'total_files': total_files,
            'total_size': total_size,
            'total_size_human': format_file_size(total_size),
            'deleted': delete_result['deleted'],
            'failed': delete_result['failed'],
            'database_records_deleted': db_deleted,
            'success_rate': round(success_rate, 2),
            'errors': delete_result['errors'][:10],
            'client_ip': client_ip,
            'cleanup_type': 'files_only_protected',
            'folders_protected': True,
            'note': '🛡️ Tất cả thư mục được bảo vệ hoàn toàn - chỉ xóa file'
        })
        
    except Exception as e:
        error_msg = f"🛡️ Protected cleanup error: {str(e)}"
        logger.error(error_msg)
        return jsonify({
            'success': False,
            'error': error_msg
        }), 500

def list_all_items_with_type(bucket_name, folder_path=""):
    """
    Lấy tất cả items và phân loại rõ ràng file vs folder
    Dùng cho storage info và full cleanup
    """
    if DEMO_MODE:
        return []
    
    try:
        all_items = []
        
        result = supabase.storage.from_(bucket_name).list(folder_path)
        if not result:
            return all_items
            
        for item in result:
            item_name = item.get('name', '')
            if not item_name:
                continue
                
            if folder_path:
                full_path = f"{folder_path}/{item_name}"
            else:   
                full_path = item_name
            
            # Phân loại dựa trên metadata Supabase
            item_id = item.get('id')
            item_size = item.get('size')
            item_mimetype = item.get('mimetype')
            
            # File: có metadata rõ ràng hoặc có extension
            is_file = (
                item_id is not None or 
                (item_size is not None and item_size > 0) or 
                (item_mimetype is not None and item_mimetype.strip() != '') or
                ('.' in item_name and not item_name.startswith('.') and not item_name.endswith('/'))
            )
            
            if is_file:
                all_items.append({
                    'name': item_name,
                    'path': full_path,
                    'type': 'file',
                    'size': item_size or 0,
                    'mimetype': item_mimetype or '',
                    'last_modified': item.get('updated_at', item.get('created_at', '')),
                    'metadata': item
                })
                logger.debug(f"✓ Detected FILE: {full_path}")
            else:
                # Folder - thêm vào danh sách
                all_items.append({
                    'name': item_name,
                    'path': full_path,
                    'type': 'folder',
                    'size': 0,
                    'last_modified': item.get('updated_at', item.get('created_at', '')),
                    'metadata': item
                })
                logger.debug(f"📁 Detected FOLDER: {full_path}")
                
                # Đệ quy vào folder
                try:
                    subfolder_items = list_all_items_with_type(bucket_name, full_path)
                    all_items.extend(subfolder_items)
                except Exception as e:
                    logger.warning(f"Cannot access subfolder {full_path}: {str(e)}")
        
        return all_items
        
    except Exception as e:
        logger.error(f"Error listing items in {folder_path}: {str(e)}")
        return []

def delete_items_batch(bucket_name, items_to_delete, batch_size=10):
    """
    Xóa items theo batch để tránh timeout và rate limit
    """
    if not items_to_delete:
        return {'deleted': 0, 'failed': 0, 'errors': []}
    
    deleted_count = 0
    failed_count = 0
    errors = []
    
    # Chia thành các batch nhỏ
    for i in range(0, len(items_to_delete), batch_size):
        batch = items_to_delete[i:i + batch_size]
        batch_paths = [item['path'] for item in batch]
        
        try:
            logger.info(f"🗑️ Deleting batch {i//batch_size + 1}: {len(batch_paths)} items")
            logger.debug(f"Batch paths: {batch_paths}")
            
            # Xóa theo batch
            result = supabase.storage.from_(bucket_name).remove(batch_paths)
            
            # Kiểm tra kết quả
            if result:
                # Nếu có kết quả trả về, kiểm tra từng item
                if isinstance(result, list):
                    for idx, res in enumerate(result):
                        if res.get('error'):
                            error_msg = res.get('error', {}).get('message', 'Unknown error')
                            if 'not found' in error_msg.lower() or 'does not exist' in error_msg.lower():
                                deleted_count += 1
                                logger.info(f"✅ Item already deleted: {batch_paths[idx]}")
                            else:
                                failed_count += 1
                                errors.append(f"❌ {batch_paths[idx]}: {error_msg}")
                                logger.error(f"❌ Failed to delete {batch_paths[idx]}: {error_msg}")
                        else:
                            deleted_count += 1
                            logger.info(f"✅ Successfully deleted: {batch_paths[idx]}")
                else:
                    # Nếu không có error, coi như tất cả đã xóa thành công
                    deleted_count += len(batch_paths)
                    logger.info(f"✅ Batch deleted successfully: {len(batch_paths)} items")
            else:
                # Nếu không có result, coi như thành công
                deleted_count += len(batch_paths)
                logger.info(f"✅ Batch processed: {len(batch_paths)} items")
                
        except Exception as e:
            error_str = str(e).lower()
            # Xử lý từng item trong batch khi có lỗi
            for path in batch_paths:
                if any(keyword in error_str for keyword in ['not found', 'does not exist', 'not exist']):
                    deleted_count += 1
                    logger.info(f"✅ Item already deleted: {path}")
                else:
                    failed_count += 1
                    error_msg = f"❌ Failed to delete {path}: {str(e)}"
                    errors.append(error_msg)
                    logger.error(error_msg)
        
        # Delay giữa các batch
        if i + batch_size < len(items_to_delete):
            time.sleep(0.5)
            logger.info(f"⏳ Processed {min(i + batch_size, len(items_to_delete))}/{len(items_to_delete)} items...")
    
    return {
        'deleted': deleted_count,
        'failed': failed_count,
        'errors': errors
    }
@app.route('/api/storage/cleanup', methods=['POST'])
def cleanup_storage():
    """API để dọn dẹp tất cả file VÀ thư mục - FIXED VERSION"""
    try:
        if DEMO_MODE:
            return jsonify({
                'success': True,
                'message': '🔧 Demo mode: Mô phỏng xóa tất cả',
                'demo_mode': True,
                'total_items': 0,
                'deleted': 0,
                'failed': 0,
                'errors': []
            })
        
        client_ip = get_client_ip()
        logger.warning(f"💥 FULL STORAGE CLEANUP initiated from IP: {client_ip}")
        
        # Lấy tất cả items
        logger.info("📋 Scanning ALL items (files + folders)...")
        all_items = list_all_items_with_type(SUPABASE_BUCKET)
        
        if not all_items:
            return jsonify({
                'success': True,
                'message': '✅ Storage đã trống',
                'total_items': 0,
                'deleted': 0,
                'failed': 0,
                'errors': []
            })
        
        # Phân loại
        files = [item for item in all_items if item['type'] == 'file']
        folders = [item for item in all_items if item['type'] == 'folder']
        
        total_files = len(files)
        total_folders = len(folders)
        total_size = sum(item.get('size', 0) for item in files)
        
        logger.info(f"💥 FULL CLEANUP TARGET:")
        logger.info(f"   📄 Files: {total_files}")
        logger.info(f"   📁 Folders: {total_folders}")
        logger.info(f"   💾 Total size: {format_file_size(total_size)}")
        
        # Log sample items
        logger.info("📋 Sample items to delete:")
        sample_files = files[:3]
        sample_folders = folders[:3]
        for i, item in enumerate(sample_files):
            logger.info(f"  📄 {i+1}. {item['path']} ({format_file_size(item.get('size', 0))})")
        for i, item in enumerate(sample_folders):
            logger.info(f"  📁 {i+1}. {item['path']}")
        
        # STRATEGY: Xóa TẤT CẢ cùng lúc (files + folders)
        # Sắp xếp theo độ sâu (deep first) để tránh lỗi folder không rỗng
        all_items_sorted = sorted(all_items, key=lambda x: (
            x['path'].count('/'),  # Độ sâu
            x['type'] == 'folder'  # File trước, folder sau
        ), reverse=True)
        
        logger.info(f"🚀 Starting FULL deletion of {len(all_items_sorted)} items...")
        logger.info("📋 Deletion order (deep-first):")
        for i, item in enumerate(all_items_sorted[:5]):
            logger.info(f"  {i+1}. [{item['type'].upper()}] {item['path']}")
        
        # Thực hiện xóa
        delete_result = delete_items_batch(SUPABASE_BUCKET, all_items_sorted, batch_size=8)
        
        # Database cleanup
        db_deleted = 0
        try:
            logger.info("🗄️ Cleaning database records...")
            db_result = supabase.table('submissions').delete().neq('id', 0).execute()
            db_deleted = len(db_result.data) if db_result.data else 0
            logger.info(f"🗄️ Cleaned {db_deleted} database records")
        except Exception as e:
            logger.warning(f"⚠️ Database cleanup failed: {str(e)}")
        
        # Kết quả
        total_items = total_files + total_folders
        success_rate = (delete_result['deleted'] / total_items * 100) if total_items > 0 else 100
        
        message = f"💥 XÓA {delete_result['deleted']}/{total_items} items"
        message += f" ({total_files} files + {total_folders} folders)"
        if delete_result['failed'] > 0:
            message += f" (❌ {delete_result['failed']} lỗi)"
        if db_deleted > 0:
            message += f" (🗄️ DB: {db_deleted})"
        
        logger.warning(f"💥 FULL CLEANUP COMPLETED: {message}")
        logger.info(f"📊 Success rate: {success_rate:.1f}%")
        
        return jsonify({
            'success': True,
            'message': message,
            'total_items': total_items,
            'total_files': total_files,
            'total_folders': total_folders,
            'total_size': total_size,
            'total_size_human': format_file_size(total_size),
            'deleted': delete_result['deleted'],
            'failed': delete_result['failed'],
            'database_records_deleted': db_deleted,
            'success_rate': round(success_rate, 2),
            'errors': delete_result['errors'][:15],
            'client_ip': client_ip,
            'cleanup_type': 'full',
            'strategy': 'deep_first_batch_delete'
        })
        
    except Exception as e:
        error_msg = f"💥 Full cleanup error: {str(e)}"
        logger.error(error_msg)
        logger.exception("Full cleanup exception details:")
        return jsonify({
            'success': False,
            'error': error_msg,
            'cleanup_type': 'full'
        }), 500


@app.route('/api/storage/info', methods=['GET'])
def storage_info():
    """Thông tin storage với phân loại chính xác"""
    try:
        if DEMO_MODE:
            return jsonify({
                'success': True,
                'demo_mode': True,
                'total_files': 0,
                'total_folders': 0,
                'total_size': 0,
                'message': '🔧 Demo mode'
            })

        all_items = list_all_items_with_type(SUPABASE_BUCKET)
        
        files = [item for item in all_items if item['type'] == 'file']
        folders = [item for item in all_items if item['type'] == 'folder']

        total_files = len(files)
        total_folders = len(folders)
        total_size = sum(file.get('size', 0) for file in files)

        # Folder stats
        folder_stats = {}
        for file in files:
            folder_name = file['path'].split('/')[0] if '/' in file['path'] else 'root'
            if folder_name not in folder_stats:
                folder_stats[folder_name] = {'count': 0, 'size': 0}
            folder_stats[folder_name]['count'] += 1
            folder_stats[folder_name]['size'] += file.get('size', 0)

        folder_list = [
            {
                'name': name,
                'file_count': stats['count'],
                'total_size': stats['size'],
                'size_human': format_file_size(stats['size'])
            }
            for name, stats in folder_stats.items()
        ]
        folder_list.sort(key=lambda x: x['total_size'], reverse=True)

        # File types
        file_types = {}
        for file in files:
            if '.' in file['path']:
                ext = file['path'].split('.')[-1].lower()
                if ext not in file_types:
                    file_types[ext] = {'count': 0, 'size': 0}
                file_types[ext]['count'] += 1
                file_types[ext]['size'] += file.get('size', 0)

        return jsonify({
            'success': True,
            'total_files': total_files,
            'total_folders': total_folders,
            'total_items': total_files + total_folders,
            'total_size': total_size,
            'total_size_human': format_file_size(total_size),
            'folder_stats': folder_list,
            'bucket': SUPABASE_BUCKET,
            'recent_files': sorted(files, key=lambda x: x.get('last_modified', ''), reverse=True)[:10],
            'file_types': file_types,
            'cleanup_options': {
                'files_only': '🛡️ Xóa chỉ file - Bảo vệ thư mục',
                'full': '💥 Xóa tất cả file và thư mục'
            }
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/storage/cleanup-files-confirm', methods=['POST']) 
def cleanup_files_confirm():
    """Xác nhận trước khi xóa chỉ file (BẢO VỆ thư mục)"""
    try:
        confirm_code = request.json.get('confirm_code', '') if request.is_json else ''
        expected_code = "DELETE_FILES_KEEP_FOLDERS"
        
        if confirm_code != expected_code:
            return jsonify({
                'success': False,
                'error': f'❌ Nhập mã xác nhận: "{expected_code}"',
                'required_code': expected_code,
                'note': '🛡️ Thao tác này CHỈ xóa file - THƯ MỤC ĐƯỢC BẢO VỆ'
            }), 400
        
        logger.info("🛡️ Confirmed: FILES-ONLY cleanup (folders protected)")
        return cleanup_files_only()
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/storage/cleanup-confirm', methods=['POST']) 
def cleanup_confirm():
    """Xác nhận trước khi xóa tất cả"""
    try:
        confirm_code = request.json.get('confirm_code', '') if request.is_json else ''
        expected_code = "DELETE_ALL_FILES_AND_FOLDERS"
        
        if confirm_code != expected_code:
            return jsonify({
                'success': False,
                'error': f'❌ Nhập mã xác nhận: "{expected_code}"',
                'required_code': expected_code,
                'note': '💥 Thao tác này XÓA TẤT CẢ'
            }), 400
        
        logger.info("💥 Confirmed: FULL cleanup")
        return cleanup_storage()
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
def get_all_storage_files(supabase, bucket_name, path="", max_files=5000):
    """
    Lấy tất cả files trong storage một cách recursive
    """
    all_files = []
    folders_to_process = [path] if path else [""]
    processed_folders = set()
    
    while folders_to_process:
        current_path = folders_to_process.pop(0)
        
        # Tránh xử lý folder trùng lặp
        if current_path in processed_folders:
            continue
        processed_folders.add(current_path)
        
        try:
            # Lấy items trong folder hiện tại
            items = supabase.storage.from_(bucket_name).list(
                path=current_path, 
                options={"limit": 1000}
            )
            
            if not items:
                continue
                
            for item in items:
                item_name = item.get('name', '')
                if not item_name:
                    continue
                    
                # Tạo full path
                if current_path:
                    full_path = f"{current_path}/{item_name}"
                else:
                    full_path = item_name
                
                # Kiểm tra xem đây là file hay folder
                # Folder thường có size = 0 hoặc None và updated_at = None
                metadata = item.get('metadata', {}) or {}
                file_size = metadata.get('size', 0) or 0
                updated_at = item.get('updated_at')
                
                # Nếu là folder (size = 0 và không có updated_at)
                if file_size == 0 and updated_at is None:
                    # Thêm folder vào queue để xử lý
                    folders_to_process.append(full_path)
                else:
                    # Đây là file thật
                    all_files.append({
                        'name': item_name,
                        'full_path': full_path,
                        'folder': current_path,
                        'size': file_size,
                        'updated_at': updated_at,
                        'metadata': item
                    })
                
                # Giới hạn số lượng files để tránh timeout
                if len(all_files) >= max_files:
                    break
            
            if len(all_files) >= max_files:
                break
                
        except Exception as e:
            print(f"Lỗi khi lấy files từ folder '{current_path}': {str(e)}")
            continue
    
    return all_files

# API để lấy preview cấu trúc thư mục trước khi download (FIXED)
@app.route('/api/preview/storage-structure', methods=['GET'])
def preview_storage_structure():
    """
    API để xem preview cấu trúc storage trước khi download
    """
    try:
        if DEMO_MODE:
            return jsonify({
                'success': False,
                'error': 'Tính năng này không khả dụng ở Demo Mode'
            }), 400
        
        print("🔍 Đang quét cấu trúc storage...")
        
        # Lấy tất cả files từ storage
        all_files = get_all_storage_files(supabase, SUPABASE_BUCKET)
        
        if not all_files:
            return jsonify({
                'success': True,
                'message': 'Không tìm thấy files nào trong storage',
                'data': {
                    'folders': {},
                    'root_files': [],
                    'statistics': {
                        'total_folders': 0,
                        'total_files': 0,
                        'total_size': 0,
                        'total_size_human': '0 B'
                    }
                }
            })
        
        # Phân tích cấu trúc
        folders_structure = {}
        root_files = []
        total_size = 0
        
        for file_info in all_files:
            file_name = file_info['name']
            full_path = file_info['full_path']
            folder = file_info['folder']
            file_size = file_info['size']
            updated_at = file_info['updated_at']
            
            total_size += file_size
            
            if folder and folder != "":
                # File trong subfolder
                if folder not in folders_structure:
                    folders_structure[folder] = {
                        'name': folder,
                        'files': [],
                        'file_count': 0,
                        'total_size': 0
                    }
                
                folders_structure[folder]['files'].append({
                    'name': file_name,
                    'full_path': full_path,
                    'size': file_size,
                    'size_human': format_file_size(file_size),
                    'updated_at': updated_at
                })
                folders_structure[folder]['file_count'] += 1
                folders_structure[folder]['total_size'] += file_size
                
            else:
                # File ở root
                root_files.append({
                    'name': file_name,
                    'full_path': full_path,
                    'size': file_size,
                    'size_human': format_file_size(file_size),
                    'updated_at': updated_at
                })
        
        # Format folders
        for folder_name, folder_info in folders_structure.items():
            folder_info['total_size_human'] = format_file_size(folder_info['total_size'])
        
        # Tính toán thống kê
        total_files = len(all_files)
        
        print(f"✅ Quét hoàn thành: {total_files} files trong {len(folders_structure)} folders")
        
        return jsonify({
            'success': True,
            'data': {
                'folders': folders_structure,
                'root_files': root_files,
                'statistics': {
                    'total_folders': len(folders_structure),
                    'total_files': total_files,
                    'total_size': total_size,
                    'total_size_human': format_file_size(total_size),
                    'folders_with_files': len([f for f in folders_structure.values() if f['file_count'] > 0]),
                    'root_file_count': len(root_files)
                }
            }
        })
        
    except Exception as e:
        print(f"❌ Lỗi lấy cấu trúc storage: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Lỗi lấy cấu trúc storage: {str(e)}'
        }), 500
@app.route('/api/download/all-folders', methods=['GET', 'POST'])
def download_all_folders():
    """
    API để download tất cả folders và files từ Supabase Storage về máy local
    Hỗ trợ incremental sync - chỉ tải file mới/thay đổi từ lần 2
    
    Query Parameters:
    - format: 'zip' hoặc 'folders' (default: 'folders')
    - path: đường dẫn lưu local (default: './downloads')
    - include_metadata: true/false - có lưu metadata không (default: true)
    - force_full: true/false - buộc download toàn bộ (default: false)
    - sync_mode: 'incremental' hoặc 'full' (default: 'incremental')
    """
    try:
        if DEMO_MODE:
            return jsonify({
                'success': False,
                'error': 'Tính năng này không khả dụng ở Demo Mode'
            }), 400
        
        # Lấy parameters
        download_format = request.args.get('format', 'folders').lower()
        local_path = request.args.get('path', './downloads')
        include_metadata = request.args.get('include_metadata', 'true').lower() == 'true'
        force_full = request.args.get('force_full', 'false').lower() == 'true'
        sync_mode = request.args.get('sync_mode', 'incremental').lower()
        
        # Tạo thư mục download nếu chưa có
        download_dir = Path(local_path)
        download_dir.mkdir(parents=True, exist_ok=True)
        
        # Đường dẫn file sync state
        sync_state_file = download_dir / '.sync_state.json'
        
        print(f"🚀 Bắt đầu {'full' if force_full or sync_mode == 'full' else 'incremental'} download...")
        print(f"📁 Lưu tại: {download_dir.absolute()}")
        print(f"📦 Format: {download_format}")
        
        # Đọc sync state từ lần download trước (nếu có)
        previous_sync_state = {}
        is_first_sync = True
        
        if sync_state_file.exists() and not force_full and sync_mode == 'incremental':
            try:
                with open(sync_state_file, 'r', encoding='utf-8') as f:
                    previous_sync_state = json.load(f)
                is_first_sync = False
                print(f"📋 Tìm thấy sync state từ lần trước: {previous_sync_state.get('last_sync', 'N/A')}")
            except Exception as e:
                print(f"⚠️ Không thể đọc sync state: {e}. Sẽ thực hiện full sync.")
                is_first_sync = True
        
        # Lấy tất cả files từ storage
        try:
            all_files = get_all_storage_files(supabase, SUPABASE_BUCKET)
            
            if not all_files:
                return jsonify({
                    'success': False,
                    'error': 'Không tìm thấy file nào trong storage'
                }), 404
            
            print(f"📊 Tìm thấy {len(all_files)} files trên storage")
            
        except Exception as e:
            return jsonify({
                'success': False,
                'error': f'Lỗi lấy danh sách files: {str(e)}'
            }), 500
        
        # Lấy danh sách folders từ storage để tạo cấu trúc thư mục
        folders_on_storage = set()
        files_to_process = []
        
        # Phân loại files và xác định files cần download
        for file_info in all_files:
            folder = file_info['folder']
            file_path = file_info['full_path']
            
            # Thêm folder vào danh sách
            if folder and folder != "":
                folders_on_storage.add(folder)
                # Thêm các parent folders nếu có nested structure
                folder_parts = folder.split('/')
                for i in range(1, len(folder_parts) + 1):
                    parent_folder = '/'.join(folder_parts[:i])
                    folders_on_storage.add(parent_folder)
            
            # Kiểm tra xem file có cần download không
            should_download = True
            
            if not is_first_sync and sync_mode == 'incremental':
                # So sánh với sync state trước
                previous_file_info = previous_sync_state.get('files', {}).get(file_path)
                
                if previous_file_info:
                    # So sánh updated_at và size
                    current_updated = file_info.get('updated_at', '')
                    previous_updated = previous_file_info.get('updated_at', '')
                    current_size = file_info.get('size', 0)
                    previous_size = previous_file_info.get('size', 0)
                    
                    if (current_updated == previous_updated and 
                        current_size == previous_size):
                        # File không thay đổi, kiểm tra xem file local có tồn tại không
                        if folder:
                            local_file_path = download_dir / folder / file_info['name']
                        else:
                            local_file_path = download_dir / file_info['name']
                        
                        if local_file_path.exists():
                            should_download = False
                            print(f"⏭️ Skip unchanged file: {file_path}")
            
            if should_download:
                files_to_process.append(file_info)
        
        print(f"📁 Tìm thấy {len(folders_on_storage)} folders trên storage")
        print(f"📄 Cần download {len(files_to_process)} files")
        
        # Tạo tất cả folders trước khi download
        print("🏗️ Tạo cấu trúc thư mục...")
        for folder_name in sorted(folders_on_storage):
            folder_path = download_dir / folder_name
            folder_path.mkdir(parents=True, exist_ok=True)
            print(f"   📁 Created: {folder_path}")
        
        # Nếu không có file nào cần download
        if not files_to_process:
            print("✅ Tất cả files đã được sync, không có gì để download!")
            
            return jsonify({
                'success': True,
                'message': 'Tất cả files đã được sync, không có file mới để download',
                'data': {
                    'download_path': str(download_dir.absolute()),
                    'sync_type': 'incremental',
                    'statistics': {
                        'total_folders': len(folders_on_storage),
                        'total_files_on_storage': len(all_files),
                        'files_to_download': 0,
                        'already_synced': len(all_files),
                        'total_size': 0
                    }
                }
            })
        
        # Phân loại files cần download theo folders
        folders_structure = {}
        root_files = []
        
        for file_info in files_to_process:
            folder = file_info['folder']
            
            if folder and folder != "":
                if folder not in folders_structure:
                    folders_structure[folder] = []
                folders_structure[folder].append(file_info)
            else:
                root_files.append(file_info)
        
        download_results = {
            'folders': {},
            'root_files': [],
            'total_files': 0,
            'total_size': 0,
            'errors': [],
            'skipped_files': len(all_files) - len(files_to_process)
        }
        
        # Function để tính checksum của file
        def calculate_file_checksum(file_path):
            try:
                hash_md5 = hashlib.md5()
                with open(file_path, "rb") as f:
                    for chunk in iter(lambda: f.read(4096), b""):
                        hash_md5.update(chunk)
                return hash_md5.hexdigest()
            except:
                return None
        
        # Function để download một file
        def download_single_file(file_info, local_file_path):
            try:
                storage_path = file_info['full_path']
                
                # Download file từ Supabase
                file_data = supabase.storage.from_(SUPABASE_BUCKET).download(storage_path)
                
                if not file_data:
                    return {
                        'success': False,
                        'error': f'Không thể download {storage_path}',
                        'path': storage_path
                    }
                
                # Tạo thư mục nếu cần (đã tạo trước đó nhưng đảm bảo)
                local_file_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Ghi file
                with open(local_file_path, 'wb') as f:
                    f.write(file_data)
                
                file_size = len(file_data)
                
                # Tính checksum để verify
                checksum = calculate_file_checksum(local_file_path)
                
                return {
                    'success': True,
                    'storage_path': storage_path,
                    'local_path': str(local_file_path),
                    'size': file_size,
                    'checksum': checksum,
                    'metadata': file_info
                }
                
            except Exception as e:
                return {
                    'success': False,
                    'error': str(e),
                    'path': file_info['full_path']
                }
        
        # Tạo current sync state để lưu
        current_sync_state = {
            'last_sync': datetime.now().isoformat(),
            'sync_type': 'full' if is_first_sync else 'incremental',
            'total_files_on_storage': len(all_files),
            'files_downloaded': 0,
            'files': {}
        }
        
        # Download files theo format
        if download_format == 'zip':
            # Tạo file zip với timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            sync_type = 'full' if is_first_sync else 'incremental'
            zip_filename = f"supabase_storage_{sync_type}_{timestamp}.zip"
            zip_path = download_dir / zip_filename
            
            # Tạo thư mục temp
            temp_dir = download_dir / 'temp'
            temp_dir.mkdir(exist_ok=True)
            
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                
                # Download files trong folders
                for folder_name, files in folders_structure.items():
                    print(f"📁 Processing folder: {folder_name} ({len(files)} files)")
                    
                    folder_results = {
                        'name': folder_name,
                        'files': [],
                        'total_files': len(files),
                        'success_count': 0,
                        'error_count': 0
                    }
                    
                    for file_info in files:
                        temp_file_path = temp_dir / file_info['full_path']
                        result = download_single_file(file_info, temp_file_path)
                        
                        if result['success']:
                            # Thêm vào zip với đúng cấu trúc thư mục
                            zipf.write(temp_file_path, file_info['full_path'])
                            
                            folder_results['files'].append(result)
                            folder_results['success_count'] += 1
                            download_results['total_files'] += 1
                            download_results['total_size'] += result['size']
                            
                            # Cập nhật sync state
                            current_sync_state['files'][file_info['full_path']] = {
                                'updated_at': file_info.get('updated_at'),
                                'size': file_info.get('size'),
                                'checksum': result['checksum']
                            }
                            
                            # Xóa file temp
                            temp_file_path.unlink()
                            
                        else:
                            folder_results['error_count'] += 1
                            download_results['errors'].append(result)
                    
                    download_results['folders'][folder_name] = folder_results
                
                # Download root files
                if root_files:
                    print(f"📄 Processing root files: {len(root_files)} files")
                    
                    for file_info in root_files:
                        temp_file_path = temp_dir / file_info['name']
                        result = download_single_file(file_info, temp_file_path)
                        
                        if result['success']:
                            zipf.write(temp_file_path, file_info['name'])
                            
                            download_results['root_files'].append(result)
                            download_results['total_files'] += 1
                            download_results['total_size'] += result['size']
                            
                            # Cập nhật sync state
                            current_sync_state['files'][file_info['full_path']] = {
                                'updated_at': file_info.get('updated_at'),
                                'size': file_info.get('size'),
                                'checksum': result['checksum']
                            }
                            
                            # Xóa file temp
                            temp_file_path.unlink()
                            
                        else:
                            download_results['errors'].append(result)
                
                # Thêm metadata file nếu cần
                if include_metadata:
                    metadata_content = {
                        'download_info': {
                            'timestamp': datetime.now().isoformat(),
                            'sync_type': current_sync_state['sync_type'],
                            'bucket': SUPABASE_BUCKET,
                            'total_folders': len(folders_on_storage),
                            'files_on_storage': len(all_files),
                            'files_downloaded': download_results['total_files'],
                            'files_skipped': download_results['skipped_files'],
                            'total_size': download_results['total_size'],
                            'total_size_human': format_file_size(download_results['total_size'])
                        },
                        'folders_structure': list(folders_on_storage),
                        'downloaded_folders': folders_structure,
                        'downloaded_root_files': root_files
                    }
                    
                    metadata_path = temp_dir / 'metadata.json'
                    with open(metadata_path, 'w', encoding='utf-8') as f:
                        json.dump(metadata_content, f, indent=2, ensure_ascii=False, default=str)
                    
                    zipf.write(metadata_path, 'metadata.json')
                    metadata_path.unlink()
            
            # Xóa thư mục temp
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            
            download_results['zip_file'] = str(zip_path)
            download_results['zip_size'] = zip_path.stat().st_size
            download_results['zip_size_human'] = format_file_size(zip_path.stat().st_size)
            
        else:
            # Download thành folders riêng biệt
            
            # Download files trong folders
            for folder_name, files in folders_structure.items():
                print(f"📁 Downloading folder: {folder_name} ({len(files)} files)")
                
                folder_path = download_dir / folder_name
                # Folder đã được tạo ở trên
                
                folder_results = {
                    'name': folder_name,
                    'path': str(folder_path),
                    'files': [],
                    'total_files': len(files),
                    'success_count': 0,
                    'error_count': 0
                }
                
                for file_info in files:
                    local_file_path = folder_path / file_info['name']
                    
                    result = download_single_file(file_info, local_file_path)
                    
                    if result['success']:
                        folder_results['files'].append(result)
                        folder_results['success_count'] += 1
                        download_results['total_files'] += 1
                        download_results['total_size'] += result['size']
                        
                        # Cập nhật sync state
                        current_sync_state['files'][file_info['full_path']] = {
                            'updated_at': file_info.get('updated_at'),
                            'size': file_info.get('size'),
                            'checksum': result['checksum']
                        }
                    else:
                        folder_results['error_count'] += 1
                        download_results['errors'].append(result)
                
                download_results['folders'][folder_name] = folder_results
            
            # Download root files
            if root_files:
                print(f"📄 Downloading root files: {len(root_files)} files")
                
                for file_info in root_files:
                    local_file_path = download_dir / file_info['name']
                    
                    result = download_single_file(file_info, local_file_path)
                    
                    if result['success']:
                        download_results['root_files'].append(result)
                        download_results['total_files'] += 1
                        download_results['total_size'] += result['size']
                        
                        # Cập nhật sync state
                        current_sync_state['files'][file_info['full_path']] = {
                            'updated_at': file_info.get('updated_at'),
                            'size': file_info.get('size'),
                            'checksum': result['checksum']
                        }
                    else:
                        download_results['errors'].append(result)
        
        # Cập nhật sync state với files từ previous state (files không thay đổi)
        if not is_first_sync:
            for file_path, file_data in previous_sync_state.get('files', {}).items():
                if file_path not in current_sync_state['files']:
                    # File này không được download lần này (không thay đổi)
                    current_sync_state['files'][file_path] = file_data
        
        current_sync_state['files_downloaded'] = download_results['total_files']
        
        # Lưu sync state mới
        try:
            with open(sync_state_file, 'w', encoding='utf-8') as f:
                json.dump(current_sync_state, f, indent=2, ensure_ascii=False, default=str)
            print(f"💾 Đã lưu sync state tại: {sync_state_file}")
        except Exception as e:
            print(f"⚠️ Không thể lưu sync state: {e}")
        
        # Tạo metadata file nếu cần (cho folder mode)
        if include_metadata and download_format != 'zip':
            metadata_content = {
                'download_info': {
                    'timestamp': datetime.now().isoformat(),
                    'sync_type': current_sync_state['sync_type'],
                    'bucket': SUPABASE_BUCKET,
                    'total_folders': len(folders_on_storage),
                    'files_on_storage': len(all_files),
                    'files_downloaded': download_results['total_files'],
                    'files_skipped': download_results['skipped_files'],
                    'total_size': download_results['total_size'],
                    'total_size_human': format_file_size(download_results['total_size'])
                },
                'folders_structure': list(folders_on_storage),
                'download_results': download_results
            }
            
            metadata_path = download_dir / 'download_metadata.json'
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata_content, f, indent=2, ensure_ascii=False, default=str)
            
            download_results['metadata_file'] = str(metadata_path)
        
        # Tính toán thống kê cuối
        success_count = download_results['total_files']
        error_count = len(download_results['errors'])
        skipped_count = download_results['skipped_files']
        
        print(f"✅ {'Full' if is_first_sync else 'Incremental'} sync hoàn thành!")
        print(f"📊 Thống kê:")
        print(f"   - Tổng folders: {len(folders_on_storage)}")
        print(f"   - Files trên storage: {len(all_files)}")
        print(f"   - Files downloaded: {success_count}")
        print(f"   - Files skipped: {skipped_count}")
        print(f"   - Files lỗi: {error_count}")
        print(f"   - Tổng dung lượng downloaded: {format_file_size(download_results['total_size'])}")
        
        return jsonify({
            'success': True,
            'message': f'{"Full" if is_first_sync else "Incremental"} sync hoàn thành: {success_count} files downloaded, {skipped_count} files skipped',
            'data': {
                'download_path': str(download_dir.absolute()),
                'format': download_format,
                'sync_type': current_sync_state['sync_type'],
                'statistics': {
                    'total_folders': len(folders_on_storage),
                    'files_on_storage': len(all_files),
                    'files_downloaded': success_count,
                    'files_skipped': skipped_count,
                    'files_failed': error_count,
                    'total_size': download_results['total_size'],
                    'total_size_human': format_file_size(download_results['total_size'])
                },
                'results': download_results
            }
        })
        
    except Exception as e:
        print(f"❌ Lỗi download folders: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return jsonify({
            'success': False,
            'error': f'Lỗi download: {str(e)}'
        }), 500


# Helper function để lấy danh sách tất cả folders từ storage
def get_all_folders_from_storage(supabase_client, bucket_name):
    """
    Lấy danh sách tất cả folders từ Supabase Storage
    """
    try:
        # Lấy tất cả files
        result = supabase_client.storage.from_(bucket_name).list()
        
        folders = set()
        
        def extract_folders_recursive(items, current_path=""):
            for item in items:
                item_name = item.get('name', '')
                
                if current_path:
                    full_path = f"{current_path}/{item_name}"
                else:
                    full_path = item_name
                
                # Nếu là folder (không có metadata file info)
                if item.get('metadata') is None or 'size' not in item.get('metadata', {}):
                    folders.add(full_path)
                    
                    # Recursively list contents of this folder
                    try:
                        subfolder_result = supabase_client.storage.from_(bucket_name).list(full_path)
                        extract_folders_recursive(subfolder_result, full_path)
                    except:
                        pass  # Ignore errors when listing subfolders
                else:
                    # File - extract its parent folder
                    if '/' in full_path:
                        parent_folder = '/'.join(full_path.split('/')[:-1])
                        folders.add(parent_folder)
        
        extract_folders_recursive(result)
        
        return list(folders)
        
    except Exception as e:
        print(f"Error getting folders: {e}")
        return []


# API để lấy danh sách folders
@app.route('/api/storage/folders', methods=['GET'])
def get_storage_folders():
    """
    API để lấy danh sách tất cả folders trong Supabase Storage
    """
    try:
        if DEMO_MODE:
            return jsonify({
                'success': False,
                'error': 'Tính năng này không khả dụng ở Demo Mode'
            }), 400
        
        folders = get_all_folders_from_storage(supabase, SUPABASE_BUCKET)
        
        return jsonify({
            'success': True,
            'data': {
                'folders': sorted(folders),
                'total_folders': len(folders)
            }
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Lỗi lấy danh sách folders: {str(e)}'
        }), 500

# Thay thế 2 API functions này trong file chính

# API để rename thư mục - FIXED VERSION
@app.route('/api/storage/rename-folder', methods=['POST'])
def rename_folder():
    """
    API để đổi tên thư mục trong storage - Fixed version
    """
    try:
        if DEMO_MODE:
            return jsonify({
                'success': False,
                'error': 'Tính năng này không khả dụng ở Demo Mode'
            }), 400
        
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': 'Không có dữ liệu JSON'
            }), 400
            
        old_folder_name = data.get('old_folder_name', '').strip()
        new_folder_name = data.get('new_folder_name', '').strip()
        
        if not old_folder_name or not new_folder_name:
            return jsonify({
                'success': False,
                'error': 'Tên thư mục cũ và mới không được để trống'
            }), 400
        
        if old_folder_name == new_folder_name:
            return jsonify({
                'success': False,
                'error': 'Tên thư mục mới phải khác với tên cũ'
            }), 400
        
        # Validate tên folder mới
        if '/' in new_folder_name or '\\' in new_folder_name:
            return jsonify({
                'success': False,
                'error': 'Tên thư mục không được chứa ký tự / hoặc \\'
            }), 400
        
        print(f"🔄 Đang rename folder '{old_folder_name}' → '{new_folder_name}'...")
        
        # Lấy tất cả files trong folder cũ
        all_files = get_all_storage_files(supabase, SUPABASE_BUCKET)
        folder_files = [f for f in all_files if f['folder'] == old_folder_name]
        
        if not folder_files:
            return jsonify({
                'success': False,
                'error': f'Không tìm thấy thư mục "{old_folder_name}" hoặc thư mục rỗng'
            }), 404
        
        # Kiểm tra folder mới đã tồn tại chưa
        existing_new_folder = [f for f in all_files if f['folder'] == new_folder_name]
        if existing_new_folder:
            return jsonify({
                'success': False,
                'error': f'Thư mục "{new_folder_name}" đã tồn tại'
            }), 400
        
        # Thực hiện copy + delete cho từng file (vì Supabase không có move trực tiếp)
        moved_files = []
        failed_files = []
        
        for file_info in folder_files:
            old_path = file_info['full_path']
            new_path = f"{new_folder_name}/{file_info['name']}"
            
            try:
                print(f"  📄 Moving: {old_path} → {new_path}")
                
                # Bước 1: Download file content
                download_response = supabase.storage.from_(SUPABASE_BUCKET).download(old_path)
                
                if not download_response:
                    failed_files.append({
                        'file': file_info['name'],
                        'error': 'Không thể download file từ path cũ'
                    })
                    continue
                
                # Bước 2: Upload với path mới
                upload_response = supabase.storage.from_(SUPABASE_BUCKET).upload(
                    path=new_path,
                    file=download_response,
                    file_options={
                        "content-type": file_info.get('metadata', {}).get('content-type', 'application/octet-stream')
                    }
                )
                
                # Kiểm tra upload thành công
                if hasattr(upload_response, 'error') and upload_response.error:
                    failed_files.append({
                        'file': file_info['name'],
                        'error': f'Upload failed: {upload_response.error}'
                    })
                    continue
                
                # Bước 3: Xóa file cũ
                delete_response = supabase.storage.from_(SUPABASE_BUCKET).remove([old_path])
                
                # Kiểm tra xóa thành công
                if hasattr(delete_response, 'error') and delete_response.error:
                    print(f"⚠️ Warning: Couldn't delete old file {old_path}: {delete_response.error}")
                    # Không fail toàn bộ operation vì file mới đã được tạo
                
                moved_files.append({
                    'old_path': old_path,
                    'new_path': new_path,
                    'file_name': file_info['name']
                })
                    
            except Exception as e:
                failed_files.append({
                    'file': file_info['name'],
                    'error': str(e)
                })
                print(f"❌ Error moving {file_info['name']}: {str(e)}")
        
        if len(failed_files) == len(folder_files):
            # Tất cả files đều fail
            return jsonify({
                'success': False,
                'error': 'Không thể move bất kỳ file nào',
                'details': {
                    'failed_files': failed_files
                }
            }), 500
        
        success_count = len(moved_files)
        total_count = len(folder_files)
        
        print(f"✅ Rename folder: {success_count}/{total_count} files moved successfully")
        
        # Nếu có một số files fail nhưng không phải tất cả
        if failed_files:
            return jsonify({
                'success': True,
                'message': f'Đã đổi tên thư mục "{old_folder_name}" thành "{new_folder_name}" ({success_count}/{total_count} files)',
                'warning': f'{len(failed_files)} files không thể move',
                'data': {
                    'old_folder_name': old_folder_name,
                    'new_folder_name': new_folder_name,
                    'moved_files_count': success_count,
                    'failed_files_count': len(failed_files),
                    'moved_files': moved_files,
                    'failed_files': failed_files
                }
            })
        
        return jsonify({
            'success': True,
            'message': f'Đã đổi tên thư mục "{old_folder_name}" thành "{new_folder_name}" thành công',
            'data': {
                'old_folder_name': old_folder_name,
                'new_folder_name': new_folder_name,
                'moved_files_count': success_count,
                'moved_files': moved_files
            }
        })
        
    except Exception as e:
        print(f"❌ Lỗi rename folder: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'Lỗi rename folder: {str(e)}'
        }), 500


# API để xóa thư mục - FIXED VERSION (Sử dụng POST thay vì DELETE để tránh conflict)
@app.route('/api/storage/delete-folder', methods=['POST', 'DELETE'])
def delete_folder():
    """
    API để xóa thư mục và tất cả files bên trong - Fixed version
    Hỗ trợ cả POST và DELETE methods
    """
    try:
        if DEMO_MODE:
            return jsonify({
                'success': False,
                'error': 'Tính năng này không khả dụng ở Demo Mode'
            }), 400
        
        # Xử lý data từ request
        if request.method == 'POST':
            data = request.get_json()
        else:  # DELETE method
            data = request.get_json() if request.is_json else {}
            # Nếu không có JSON data, thử lấy từ query params
            if not data:
                folder_name = request.args.get('folder_name', '').strip()
                confirm_delete = request.args.get('confirm_delete', '').lower() == 'true'
                data = {
                    'folder_name': folder_name,
                    'confirm_delete': confirm_delete
                }
        
        if not data:
            return jsonify({
                'success': False,
                'error': 'Không có dữ liệu request'
            }), 400
            
        folder_name = data.get('folder_name', '').strip()
        confirm_delete = data.get('confirm_delete', False)
        
        if not folder_name:
            return jsonify({
                'success': False,
                'error': 'Tên thư mục không được để trống'
            }), 400
        
        if not confirm_delete:
            return jsonify({
                'success': False,
                'error': 'Vui lòng xác nhận xóa thư mục bằng cách set confirm_delete = true'
            }), 400
        
        print(f"🗑️ Đang xóa folder '{folder_name}'...")
        
        # Lấy tất cả files trong folder
        all_files = get_all_storage_files(supabase, SUPABASE_BUCKET)
        folder_files = [f for f in all_files if f['folder'] == folder_name]
        
        if not folder_files:
            return jsonify({
                'success': False,
                'error': f'Không tìm thấy thư mục "{folder_name}" hoặc thư mục rỗng'
            }), 404
        
        print(f"📊 Tìm thấy {len(folder_files)} files để xóa")
        
        # Chuẩn bị danh sách paths để xóa
        file_paths = [f['full_path'] for f in folder_files]
        
        # Thực hiện xóa theo batch (Supabase có thể xóa nhiều files cùng lúc)
        deleted_files = []
        failed_files = []
        
        # Chia nhỏ thành batches để tránh timeout (20 files/batch để tăng độ ổn định)
        batch_size = 20
        total_batches = (len(file_paths) + batch_size - 1) // batch_size
        
        for i in range(0, len(file_paths), batch_size):
            batch_paths = file_paths[i:i + batch_size]
            batch_files = folder_files[i:i + batch_size]
            current_batch = i // batch_size + 1
            
            try:
                print(f"🗂️ Xóa batch {current_batch}/{total_batches}: {len(batch_paths)} files")
                
                # Xóa batch files
                delete_response = supabase.storage.from_(SUPABASE_BUCKET).remove(batch_paths)
                
                # Kiểm tra response (Supabase trả về list hoặc có thể có error)
                if hasattr(delete_response, 'error') and delete_response.error:
                    # Nếu batch fail, thử xóa từng file riêng
                    print(f"⚠️ Batch delete failed: {delete_response.error}, trying individual files...")
                    
                    for j, file_path in enumerate(batch_paths):
                        try:
                            single_response = supabase.storage.from_(SUPABASE_BUCKET).remove([file_path])
                            
                            if hasattr(single_response, 'error') and single_response.error:
                                failed_files.append({
                                    'file': batch_files[j]['name'],
                                    'path': file_path,
                                    'error': str(single_response.error)
                                })
                            else:
                                deleted_files.append({
                                    'file': batch_files[j]['name'],
                                    'path': file_path,
                                    'size': batch_files[j]['size']
                                })
                        except Exception as e:
                            failed_files.append({
                                'file': batch_files[j]['name'],
                                'path': file_path,
                                'error': str(e)
                            })
                else:
                    # Batch delete thành công
                    for file_info in batch_files:
                        deleted_files.append({
                            'file': file_info['name'],
                            'path': file_info['full_path'],
                            'size': file_info['size']
                        })
                    
            except Exception as e:
                print(f"❌ Error deleting batch {current_batch}: {str(e)}")
                # Nếu có lỗi với batch, thử xóa từng file
                for j, file_path in enumerate(batch_paths):
                    try:
                        single_response = supabase.storage.from_(SUPABASE_BUCKET).remove([file_path])
                        
                        if hasattr(single_response, 'error') and single_response.error:
                            failed_files.append({
                                'file': batch_files[j]['name'],
                                'path': file_path,
                                'error': str(single_response.error)
                            })
                        else:
                            deleted_files.append({
                                'file': batch_files[j]['name'],
                                'path': file_path,
                                'size': batch_files[j]['size']
                            })
                    except Exception as inner_e:
                        failed_files.append({
                            'file': batch_files[j]['name'],
                            'path': file_path,
                            'error': str(inner_e)
                        })
        
        # Tính toán kết quả
        success_count = len(deleted_files)
        failed_count = len(failed_files)
        total_count = len(folder_files)
        
        if success_count == 0:
            return jsonify({
                'success': False,
                'error': f'Không thể xóa bất kỳ file nào trong thư mục "{folder_name}"',
                'details': {
                    'failed_files': failed_files
                }
            }), 500
        
        # Tính tổng size đã xóa
        total_deleted_size = sum(f['size'] for f in deleted_files)
        
        print(f"✅ Xóa folder hoàn thành: {success_count}/{total_count} files")
        
        # Nếu có một số files fail
        if failed_files:
            return jsonify({
                'success': True,
                'message': f'Đã xóa thư mục "{folder_name}" ({success_count}/{total_count} files)',
                'warning': f'{failed_count} files không thể xóa',
                'data': {
                    'folder_name': folder_name,
                    'deleted_files_count': success_count,
                    'failed_files_count': failed_count,
                    'total_deleted_size': total_deleted_size,
                    'total_deleted_size_human': format_file_size(total_deleted_size),
                    'deleted_files': deleted_files,
                    'failed_files': failed_files
                }
            })
        
        return jsonify({
            'success': True,
            'message': f'Đã xóa thư mục "{folder_name}" và tất cả {success_count} files',
            'data': {
                'folder_name': folder_name,
                'deleted_files_count': success_count,
                'total_deleted_size': total_deleted_size,
                'total_deleted_size_human': format_file_size(total_deleted_size),
                'deleted_files': deleted_files
            }
        })
        
    except Exception as e:
        print(f"❌ Lỗi delete folder: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'Lỗi delete folder: {str(e)}'
        }), 500


# API để test connection Supabase
@app.route('/api/storage/test-connection', methods=['GET'])
def test_supabase_connection():
    """
    API để test kết nối Supabase
    """
    try:
        if DEMO_MODE:
            return jsonify({
                'success': True,
                'message': 'Đang chạy ở Demo Mode',
                'data': {
                    'demo_mode': True,
                    'supabase_configured': False
                }
            })
        
        # Test bằng cách list files
        test_result = supabase.storage.from_(SUPABASE_BUCKET).list(path="", options={"limit": 1})
        
        return jsonify({
            'success': True,
            'message': 'Kết nối Supabase thành công',
            'data': {
                'demo_mode': False,
                'supabase_configured': True,
                'bucket_name': SUPABASE_BUCKET,
                'supabase_url': SUPABASE_URL,
                'test_result': 'OK'
            }
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Lỗi kết nối Supabase: {str(e)}',
            'data': {
                'demo_mode': DEMO_MODE,
                'supabase_configured': bool(SUPABASE_URL and SUPABASE_KEY),
                'bucket_name': SUPABASE_BUCKET
            }
        }), 500


# API để tạo thư mục mới (Bonus function)
@app.route('/api/storage/create-folder', methods=['POST'])
def create_folder():
    """
    API để tạo thư mục mới bằng cách upload file placeholder
    """
    try:
        if DEMO_MODE:
            return jsonify({
                'success': False,
                'error': 'Tính năng này không khả dụng ở Demo Mode'
            }), 400
        
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': 'Không có dữ liệu JSON'
            }), 400
            
        folder_name = data.get('folder_name', '').strip()
        
        if not folder_name:
            return jsonify({
                'success': False,
                'error': 'Tên thư mục không được để trống'
            }), 400
        
        # Validate tên folder
        if '/' in folder_name or '\\' in folder_name:
            return jsonify({
                'success': False,
                'error': 'Tên thư mục không được chứa ký tự / hoặc \\'
            }), 400
        
        # Kiểm tra folder đã tồn tại chưa
        all_files = get_all_storage_files(supabase, SUPABASE_BUCKET)
        existing_folder = [f for f in all_files if f['folder'] == folder_name]
        
        if existing_folder:
            return jsonify({
                'success': False,
                'error': f'Thư mục "{folder_name}" đã tồn tại'
            }), 400
        
        # Tạo folder bằng cách upload file .gitkeep
        placeholder_path = f"{folder_name}/.gitkeep"
        placeholder_content = "# This file keeps the folder structure\n"
        
        upload_response = supabase.storage.from_(SUPABASE_BUCKET).upload(
            path=placeholder_path,
            file=placeholder_content.encode('utf-8'),
            file_options={
                "content-type": "text/plain"
            }
        )
        
        if hasattr(upload_response, 'error') and upload_response.error:
            return jsonify({
                'success': False,
                'error': f'Không thể tạo thư mục: {upload_response.error}'
            }), 500
        
        return jsonify({
            'success': True,
            'message': f'Đã tạo thư mục "{folder_name}" thành công',
            'data': {
                'folder_name': folder_name,
                'placeholder_file': '.gitkeep'
            }
        })
        
    except Exception as e:
        print(f"❌ Lỗi create folder: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Lỗi create folder: {str(e)}'
        }), 500

# API để lấy thông tin chi tiết của 1 thư mục
@app.route('/api/storage/folder-info/<folder_name>', methods=['GET'])
def get_folder_info(folder_name):
    """
    API để lấy thông tin chi tiết của 1 thư mục
    """
    try:
        if DEMO_MODE:
            return jsonify({
                'success': False,
                'error': 'Tính năng này không khả dụng ở Demo Mode'
            }), 400
        
        folder_name = folder_name.strip()
        if not folder_name:
            return jsonify({
                'success': False,
                'error': 'Tên thư mục không được để trống'
            }), 400
        
        print(f"📁 Đang lấy thông tin folder '{folder_name}'...")
        
        # Lấy tất cả files trong folder
        all_files = get_all_storage_files(supabase, SUPABASE_BUCKET)
        folder_files = [f for f in all_files if f['folder'] == folder_name]
        
        if not folder_files:
            return jsonify({
                'success': False,
                'error': f'Không tìm thấy thư mục "{folder_name}"'
            }), 404
        
        # Tính toán thống kê
        total_size = sum(f['size'] for f in folder_files)
        file_types = {}
        
        for file_info in folder_files:
            file_name = file_info['name']
            file_ext = file_name.split('.')[-1].lower() if '.' in file_name else 'no_extension'
            
            if file_ext not in file_types:
                file_types[file_ext] = {
                    'count': 0,
                    'total_size': 0
                }
            
            file_types[file_ext]['count'] += 1
            file_types[file_ext]['total_size'] += file_info['size']
        
        # Format file types
        for ext, info in file_types.items():
            info['total_size_human'] = format_file_size(info['total_size'])
        
        # Sắp xếp files theo size (lớn nhất trước)
        sorted_files = sorted(folder_files, key=lambda x: x['size'], reverse=True)
        
        return jsonify({
            'success': True,
            'data': {
                'folder_name': folder_name,
                'file_count': len(folder_files),
                'total_size': total_size,
                'total_size_human': format_file_size(total_size),
                'file_types': file_types,
                'files': sorted_files,
                'largest_files': sorted_files[:5],  # Top 5 files lớn nhất
                'statistics': {
                    'total_file_types': len(file_types),
                    'average_file_size': total_size // len(folder_files) if folder_files else 0,
                    'average_file_size_human': format_file_size(total_size // len(folder_files)) if folder_files else '0 B'
                }
            }
        })
        
    except Exception as e:
        print(f"❌ Lỗi lấy thông tin folder: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Lỗi lấy thông tin folder: {str(e)}'
        }), 500
      
@app.route('/api/submissions', methods=['GET'])
def get_submissions():
    try:
        # Lấy query parameters
        page = int(request.args.get('page', 1))
        limit = min(int(request.args.get('limit', 10)), 100)  # Max 100 records per page
        sort_by = request.args.get('sort_by', 'upload_time')
        sort_order = request.args.get('sort_order', 'desc').lower()
        folder_filter = request.args.get('folder', '').strip()
        search_query = request.args.get('search', '').strip()
        date_from = request.args.get('date_from', '').strip()
        date_to = request.args.get('date_to', '').strip()
        has_file_filter = request.args.get('has_file', '').strip().lower()
        
        # Validate parameters
        if page < 1:
            page = 1
        if limit < 1:
            limit = 10
        if sort_order not in ['asc', 'desc']:
            sort_order = 'desc'
        
        # Allowed sort fields
        allowed_sort_fields = ['upload_time', 'ho_ten', 'ten_de_tai', 'gio_quy_doi', 'folder_name', 'file_size']
        if sort_by not in allowed_sort_fields:
            sort_by = 'upload_time'
        
        # Handle demo mode
        if DEMO_MODE:
            # Generate demo data
            demo_submissions = []
            for i in range(1, 25):  # 24 demo records
                demo_submissions.append({
                    'id': i,
                    'ho_ten': f'Demo User {i}',
                    'ten_de_tai': f'Demo Project {i}',
                    'noi_cong_tac': f'Demo Company {i}',
                    'khoa_phong': f'Demo Department {i}',
                    'gio_quy_doi': round(i * 1.5, 2),
                    'minh_chung': f'Demo evidence {i}',
                    'ghi_chu': f'Demo note {i}',
                    'file_name': f'demo_file_{i}.pdf' if i % 2 == 0 else None,
                    'file_url': f'https://demo.example.com/demo_file_{i}.pdf' if i % 2 == 0 else None,
                    'file_size': i * 1024 if i % 2 == 0 else 0,
                    'folder_name': f'Demo Folder {(i % 5) + 1}' if i % 3 == 0 else None,
                    'upload_time': (datetime.datetime.now() - datetime.timedelta(days=i)).isoformat(),
                    'upload_ip': '127.0.0.1',
                    'storage_path': f'demo-folder-{(i % 5) + 1}/demo_file_{i}.pdf' if i % 2 == 0 else None
                })
            
            # Apply filters to demo data
            filtered_submissions = demo_submissions
            
            # Apply search filter
            if search_query:
                filtered_submissions = [
                    s for s in filtered_submissions 
                    if search_query.lower() in s['ho_ten'].lower() or 
                       search_query.lower() in s['ten_de_tai'].lower()
                ]
            
            # Apply folder filter
            if folder_filter:
                filtered_submissions = [
                    s for s in filtered_submissions 
                    if s['folder_name'] and folder_filter.lower() in s['folder_name'].lower()
                ]
            
            # Apply has_file filter
            if has_file_filter == 'true':
                filtered_submissions = [s for s in filtered_submissions if s['file_name']]
            elif has_file_filter == 'false':
                filtered_submissions = [s for s in filtered_submissions if not s['file_name']]
            
            # Apply sorting
            reverse_sort = sort_order == 'desc'
            filtered_submissions.sort(key=lambda x: x.get(sort_by, ''), reverse=reverse_sort)
            
            # Apply pagination
            offset = (page - 1) * limit
            paginated_submissions = filtered_submissions[offset:offset + limit]
            
            return jsonify({
                'success': True,
                'data': paginated_submissions,
                'pagination': {
                    'current_page': page,
                    'per_page': limit,
                    'total_records': len(filtered_submissions),
                    'total_pages': math.ceil(len(filtered_submissions) / limit),
                    'has_next': page < math.ceil(len(filtered_submissions) / limit),
                    'has_prev': page > 1
                },
                'filters': {
                    'folder': folder_filter,
                    'search': search_query,
                    'date_from': date_from,
                    'date_to': date_to,
                    'has_file': has_file_filter,
                    'sort_by': sort_by,
                    'sort_order': sort_order
                },
                'demo_mode': True
            })
        
        # Real Supabase query
        query = supabase.table('submissions').select('*')
        
        # Apply filters
        if folder_filter:
            query = query.ilike('folder_name', f'%{folder_filter}%')
        
        if search_query:
            # Search in multiple fields
            query = query.or_(f'ho_ten.ilike.%{search_query}%,ten_de_tai.ilike.%{search_query}%')
        
        if date_from:
            try:
                # Convert date format
                date_from_formatted = datetime.datetime.strptime(date_from, '%Y-%m-%d').isoformat()
                query = query.gte('upload_time', date_from_formatted)
            except ValueError:
                pass  # Invalid date format, ignore
        
        if date_to:
            try:
                # Convert date format and add end of day
                date_to_formatted = datetime.datetime.strptime(date_to, '%Y-%m-%d')
                date_to_formatted = date_to_formatted.replace(hour=23, minute=59, second=59).isoformat()
                query = query.lte('upload_time', date_to_formatted)
            except ValueError:
                pass  # Invalid date format, ignore
        
        if has_file_filter == 'true':
            query = query.not_.is_('file_name', 'null')
        elif has_file_filter == 'false':
            query = query.is_('file_name', 'null')
        
        # Get total count (before pagination)
        count_result = query.execute()
        total_records = len(count_result.data)
        
        # Apply sorting and pagination
        query = query.order(sort_by, desc=(sort_order == 'desc'))
        
        # Apply pagination
        offset = (page - 1) * limit
        query = query.limit(limit).offset(offset)
        
        # Execute query
        result = query.execute()
        
        # Process results
        submissions = []
        for submission in result.data:
            # Format file size
            file_size = submission.get('file_size', 0)
            if file_size:
                file_size_human = format_file_size(file_size)
            else:
                file_size_human = '0 B'
            
            # Format upload time
            upload_time = submission.get('upload_time')
            if upload_time:
                try:
                    upload_datetime = datetime.datetime.fromisoformat(upload_time.replace('Z', '+00:00'))
                    upload_time_formatted = upload_datetime.strftime('%d/%m/%Y %H:%M')
                except:
                    upload_time_formatted = upload_time
            else:
                upload_time_formatted = 'N/A'
            
            processed_submission = {
                **submission,
                'file_size_human': file_size_human,
                'upload_time_formatted': upload_time_formatted,
                'has_file': bool(submission.get('file_name')),
                'folder_display': submission.get('folder_name') or 'Không có thư mục'
            }
            
            submissions.append(processed_submission)
        
        # Calculate pagination info
        total_pages = math.ceil(total_records / limit)
        
        return jsonify({
            'success': True,
            'data': submissions,
            'pagination': {
                'current_page': page,
                'per_page': limit,
                'total_records': total_records,
                'total_pages': total_pages,
                'has_next': page < total_pages,
                'has_prev': page > 1,
                'offset': offset
            },
            'filters': {
                'folder': folder_filter,
                'search': search_query,
                'date_from': date_from,
                'date_to': date_to,
                'has_file': has_file_filter,
                'sort_by': sort_by,
                'sort_order': sort_order
            },
            'demo_mode': False
        })
        
    except Exception as e:
        print(f"Error in get_submissions: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'Lỗi lấy danh sách submissions: {str(e)}'
        }), 500

@app.route('/api/submissions/<int:submission_id>', methods=['GET'])
def get_submission_detail(submission_id):
    """API để lấy chi tiết một submission"""
    try:
        if DEMO_MODE:
            # Return demo data
            return jsonify({
                'success': True,
                'data': {
                    'id': submission_id,
                    'ho_ten': f'Demo User {submission_id}',
                    'ten_de_tai': f'Demo Project {submission_id}',
                    'noi_cong_tac': f'Demo Company {submission_id}',
                    'khoa_phong': f'Demo Department {submission_id}',
                    'gio_quy_doi': submission_id * 1.5,
                    'minh_chung': f'Demo evidence {submission_id}',
                    'ghi_chu': f'Demo note {submission_id}',
                    'file_name': f'demo_file_{submission_id}.pdf',
                    'file_url': f'https://demo.example.com/demo_file_{submission_id}.pdf',
                    'file_size': submission_id * 1024,
                    'file_size_human': format_file_size(submission_id * 1024),
                    'folder_name': f'Demo Folder {submission_id}',
                    'upload_time': datetime.datetime.now().isoformat(),
                    'upload_ip': '127.0.0.1',
                    'storage_path': f'demo-folder-{submission_id}/demo_file_{submission_id}.pdf'
                },
                'demo_mode': True
            })
        
        # Real query
        result = supabase.table('submissions').select('*').eq('id', submission_id).single().execute()
        
        if not result.data:
            return jsonify({
                'success': False,
                'error': 'Không tìm thấy submission'
            }), 404
        
        submission = result.data
        
        # Add formatted fields
        submission['file_size_human'] = format_file_size(submission.get('file_size', 0))
        submission['has_file'] = bool(submission.get('file_name'))
        submission['folder_display'] = submission.get('folder_name') or 'Không có thư mục'
        
        # Format upload time
        upload_time = submission.get('upload_time')
        if upload_time:
            try:
                upload_datetime = datetime.datetime.fromisoformat(upload_time.replace('Z', '+00:00'))
                submission['upload_time_formatted'] = upload_datetime.strftime('%d/%m/%Y %H:%M:%S')
            except:
                submission['upload_time_formatted'] = upload_time
        
        return jsonify({
            'success': True,
            'data': submission
        })
        
    except Exception as e:
        print(f"Error in get_submission_detail: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Lỗi lấy chi tiết submission: {str(e)}'
        }), 500

@app.route('/api/submissions/<int:submission_id>', methods=['PUT'])
def update_submission(submission_id):
    """API để cập nhật một submission"""
    try:
        if DEMO_MODE:
            return jsonify({
                'success': True,
                'message': 'Demo mode: Cập nhật thành công (giả lập)',
                'demo_mode': True
            })
        
        # Get request data
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': 'Không có dữ liệu để cập nhật'
            }), 400
        
        # Allowed fields to update
        allowed_fields = [
            'ho_ten', 'ten_de_tai', 'noi_cong_tac', 'khoa_phong', 
            'gio_quy_doi', 'minh_chung', 'ghi_chu', 'folder_name'
        ]
        
        # Filter and validate data
        update_data = {}
        for field in allowed_fields:
            if field in data:
                value = data[field]
                if field == 'gio_quy_doi':
                    try:
                        value = float(value)
                    except (ValueError, TypeError):
                        value = 0.0
                elif field == 'folder_name' and value:
                    # Validate folder name
                    safe_folder_name = secure_folder_name(value)
                    if not safe_folder_name:
                        return jsonify({
                            'success': False,
                            'error': 'Tên thư mục không hợp lệ'
                        }), 400
                    value = safe_folder_name
                
                update_data[field] = value
        
        if not update_data:
            return jsonify({
                'success': False,
                'error': 'Không có dữ liệu hợp lệ để cập nhật'
            }), 400
        
        # Update in database
        result = supabase.table('submissions').update(update_data).eq('id', submission_id).execute()
        
        if not result.data:
            return jsonify({
                'success': False,
                'error': 'Không tìm thấy hoặc không thể cập nhật submission'
            }), 404
        
        return jsonify({
            'success': True,
            'message': 'Cập nhật submission thành công',
            'data': result.data[0]
        })
        
    except Exception as e:
        print(f"Error in update_submission: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Lỗi cập nhật submission: {str(e)}'
        }), 500

@app.route('/api/submissions/<int:submission_id>', methods=['DELETE'])
def delete_submission(submission_id):
    """API để xóa một submission"""
    try:
        if DEMO_MODE:
            return jsonify({
                'success': True,
                'message': 'Demo mode: Xóa thành công (giả lập)',
                'demo_mode': True
            })
        
        # Get submission info first
        submission_result = supabase.table('submissions').select('*').eq('id', submission_id).single().execute()
        
        if not submission_result.data:
            return jsonify({
                'success': False,
                'error': 'Không tìm thấy submission'
            }), 404
        
        submission = submission_result.data
        storage_path = submission.get('storage_path')
        
        # Delete file from storage if exists
        if storage_path:
            try:
                delete_result = supabase.storage.from_(SUPABASE_BUCKET).remove([storage_path])
                print(f"File deleted from storage: {storage_path}")
            except Exception as storage_error:
                print(f"Error deleting file from storage: {str(storage_error)}")
                # Continue with database deletion even if file deletion fails
        
        # Delete from database
        delete_result = supabase.table('submissions').delete().eq('id', submission_id).execute()
        
        if not delete_result.data:
            return jsonify({
                'success': False,
                'error': 'Không thể xóa submission'
            }), 500
        
        return jsonify({
            'success': True,
            'message': 'Xóa submission thành công',
            'deleted_file': storage_path
        })
        
    except Exception as e:
        print(f"Error in delete_submission: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Lỗi xóa submission: {str(e)}'
        }), 500

@app.route('/api/submissions/stats', methods=['GET'])
def get_submissions_stats():
    """API để lấy thống kê submissions"""
    try:
        if DEMO_MODE:
            return jsonify({
                'success': True,
                'data': {
                    'total_submissions': 24,
                    'submissions_with_files': 12,
                    'submissions_without_files': 12,
                    'total_file_size': 24576,
                    'total_file_size_human': format_file_size(24576),
                    'total_folders': 5,
                    'avg_file_size': 2048,
                    'avg_file_size_human': format_file_size(2048),
                    'submissions_by_folder': {
                        'Demo Folder 1': 5,
                        'Demo Folder 2': 4,
                        'Demo Folder 3': 3,
                        'Không có thư mục': 12
                    },
                    'submissions_by_month': {
                        '2024-01': 8,
                        '2024-02': 10,
                        '2024-03': 6
                    },
                    'file_types': {
                        'pdf': 8,
                        'docx': 3,
                        'xlsx': 1
                    }
                },
                'demo_mode': True
            })
        
        # Real statistics
        result = supabase.table('submissions').select('*').execute()
        submissions = result.data
        
        total_submissions = len(submissions)
        submissions_with_files = len([s for s in submissions if s.get('file_name')])
        submissions_without_files = total_submissions - submissions_with_files
        
        # File size statistics
        file_sizes = [s.get('file_size', 0) for s in submissions if s.get('file_size')]
        total_file_size = sum(file_sizes)
        avg_file_size = total_file_size / len(file_sizes) if file_sizes else 0
        
        # Folder statistics
        folder_counts = {}
        for submission in submissions:
            folder = submission.get('folder_name') or 'Không có thư mục'
            folder_counts[folder] = folder_counts.get(folder, 0) + 1
        
        # Monthly statistics
        monthly_counts = {}
        for submission in submissions:
            upload_time = submission.get('upload_time')
            if upload_time:
                try:
                    date = datetime.datetime.fromisoformat(upload_time.replace('Z', '+00:00'))
                    month_key = date.strftime('%Y-%m')
                    monthly_counts[month_key] = monthly_counts.get(month_key, 0) + 1
                except:
                    pass
        
        # File type statistics
        file_type_counts = {}
        for submission in submissions:
            file_name = submission.get('file_name')
            if file_name and '.' in file_name:
                ext = file_name.split('.')[-1].lower()
                file_type_counts[ext] = file_type_counts.get(ext, 0) + 1
        
        return jsonify({
            'success': True,
            'data': {
                'total_submissions': total_submissions,
                'submissions_with_files': submissions_with_files,
                'submissions_without_files': submissions_without_files,
                'total_file_size': total_file_size,
                'total_file_size_human': format_file_size(total_file_size),
                'total_folders': len([f for f in folder_counts.keys() if f != 'Không có thư mục']),
                'avg_file_size': int(avg_file_size),
                'avg_file_size_human': format_file_size(avg_file_size),
                'submissions_by_folder': folder_counts,
                'submissions_by_month': monthly_counts,
                'file_types': file_type_counts
            }
        })
        
    except Exception as e:
        print(f"Error in get_submissions_stats: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Lỗi lấy thống kê submissions: {str(e)}'
        }), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))