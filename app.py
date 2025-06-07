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
from dotenv import load_dotenv

app = Flask(__name__)
load_dotenv()
# Cấu hình Supabase
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
SUPABASE_BUCKET = os.environ.get('SUPABASE_BUCKET', 'file-uploads')

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
    
# API để tạo và quản lý thư mục thực tế trong Supabase Storage

@app.route('/api/folders/create', methods=['POST'])
def create_folder_in_storage():
    """Tạo thư mục thực tế trong Supabase Storage"""
    try:
        data = request.get_json()
        
        if not data or 'folder_name' not in data:
            return jsonify({
                'success': False,
                'error': 'Vui lòng cung cấp tên thư mục'
            }), 400
        
        folder_name = data['folder_name'].strip()
        
        if not folder_name:
            return jsonify({
                'success': False,
                'error': 'Tên thư mục không được để trống'
            }), 400
        
        # Làm sạch tên thư mục
        safe_folder_name = secure_folder_name(folder_name)
        
        if not safe_folder_name:
            return jsonify({
                'success': False,
                'error': 'Tên thư mục không hợp lệ'
            }), 400
        
        # Kiểm tra thư mục đã tồn tại chưa trong Storage
        try:
            existing_files = supabase.storage.from_(SUPABASE_BUCKET).list()
            
            # Kiểm tra xem có file nào trong thư mục này không
            folder_exists = False
            if existing_files:
                for file_item in existing_files:
                    if file_item['name'].startswith(safe_folder_name + '/'):
                        folder_exists = True
                        break
            
            if folder_exists:
                return jsonify({
                    'success': False,
                    'error': f'Thư mục "{safe_folder_name}" đã tồn tại trong Storage'
                }), 400
                
        except Exception as storage_error:
            print(f"Error checking existing folders: {str(storage_error)}")
        
        # Tạo file README.md để khởi tạo thư mục
        readme_content = f"""# Thư mục: {safe_folder_name}

Thư mục được tạo vào: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}

## Thông tin
- Tên thư mục: {safe_folder_name}
- Tên gốc: {folder_name}
- Bucket: {SUPABASE_BUCKET}

## Hướng dẫn
Upload các file vào thư mục này thông qua form upload.
"""
        
        readme_path = f"{safe_folder_name}/README.md"
        
        # Upload file README
        result = supabase.storage.from_(SUPABASE_BUCKET).upload(
            path=readme_path,
            file=readme_content.encode('utf-8'),
            file_options={
                "content-type": "text/markdown; charset=utf-8"
            }
        )
        
        if result.status_code != 200:
            return jsonify({
                'success': False,
                'error': f'Không thể tạo thư mục: {result.status_code}'
            }), 500
        
        # Lấy URL public của file README
        readme_url = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(readme_path)
        
        # Lưu thông tin vào database
        try:
            client_ip = get_client_ip()
            supabase.table('submissions').insert({
                'ho_ten': 'System',
                'ten_de_tai': f'Tạo thư mục: {safe_folder_name}',
                'noi_cong_tac': 'System',
                'khoa_phong': 'Administration',
                'gio_quy_doi': 0,
                'minh_chung': 'Folder Creation',
                'ghi_chu': f'Thư mục "{safe_folder_name}" được tạo tự động với README.md',
                'file_name': 'README.md',
                'file_url': readme_url,
                'file_size': len(readme_content.encode('utf-8')),
                'folder_name': safe_folder_name,
                'upload_time': datetime.datetime.now().isoformat(),
                'upload_ip': client_ip,
                'storage_path': readme_path
            }).execute()
        except Exception as db_error:
            print(f"Database logging error: {str(db_error)}")
        
        return jsonify({
            'success': True,
            'message': f'Thư mục "{safe_folder_name}" đã được tạo thành công',
            'folder_name': safe_folder_name,
            'readme_url': readme_url,
            'readme_path': readme_path
        })
        
    except Exception as e:
        print(f"Error creating folder: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Lỗi tạo thư mục: {str(e)}'
        }), 500

@app.route('/api/folders/storage', methods=['GET'])
def get_folders_from_storage():
    """Lấy danh sách thư mục thực tế từ Supabase Storage"""
    try:
        # Lấy tất cả files từ Storage
        result = supabase.storage.from_(SUPABASE_BUCKET).list()
        
        if not result:
            return jsonify({
                'success': True,
                'folders': [],
                'count': 0,
                'message': 'Storage trống hoặc chưa có thư mục nào'
            })
        
        # Phân tích để tìm thư mục
        folders = {}
        
        for file_item in result:
            file_name = file_item['name']
            
            # Nếu có dấu '/' thì đây là file trong thư mục
            if '/' in file_name:
                folder_name = file_name.split('/')[0]
                
                if folder_name not in folders:
                    folders[folder_name] = {
                        'name': folder_name,
                        'file_count': 0,
                        'total_size': 0,
                        'files': [],
                        'created_at': None,
                        'updated_at': None
                    }
                
                # Thêm thông tin file
                file_size = file_item.get('metadata', {}).get('size', 0) or 0
                folders[folder_name]['file_count'] += 1
                folders[folder_name]['total_size'] += file_size
                folders[folder_name]['files'].append({
                    'name': file_name.split('/')[-1],  # Chỉ tên file
                    'full_path': file_name,
                    'size': file_size,
                    'size_human': format_file_size(file_size),
                    'created_at': file_item.get('created_at'),
                    'updated_at': file_item.get('updated_at')
                })
                
                # Cập nhật thời gian
                if not folders[folder_name]['created_at'] or file_item.get('created_at', '') < folders[folder_name]['created_at']:
                    folders[folder_name]['created_at'] = file_item.get('created_at')
                
                if not folders[folder_name]['updated_at'] or file_item.get('updated_at', '') > folders[folder_name]['updated_at']:
                    folders[folder_name]['updated_at'] = file_item.get('updated_at')
        
        # Chuyển thành list và format
        folder_list = []
        for folder_name, folder_info in folders.items():
            folder_data = {
                'name': folder_name,
                'file_count': folder_info['file_count'],
                'total_size': folder_info['total_size'],
                'total_size_human': format_file_size(folder_info['total_size']),
                'created_at': folder_info['created_at'],
                'updated_at': folder_info['updated_at'],
                'files': folder_info['files']
            }
            folder_list.append(folder_data)
        
        # Sắp xếp theo tên
        folder_list.sort(key=lambda x: x['name'])
        
        return jsonify({
            'success': True,
            'folders': folder_list,
            'count': len(folder_list),
            'message': f'Tìm thấy {len(folder_list)} thư mục trong Storage'
        })
        
    except Exception as e:
        print(f"Error getting folders from storage: {str(e)}")
        return jsonify({
            'success': False,
            'folders': [],
            'error': f'Lỗi đọc Storage: {str(e)}'
        }), 500

@app.route('/api/folders/storage/<path:folder_name>/files', methods=['GET'])
def get_files_in_storage_folder(folder_name):
    """Lấy danh sách files trong thư mục cụ thể từ Storage"""
    try:
        folder_name = unquote(folder_name)
        
        # Lấy files trong thư mục từ Storage
        result = supabase.storage.from_(SUPABASE_BUCKET).list(folder_name)
        
        if not result:
            return jsonify({
                'success': True,
                'files': [],
                'count': 0,
                'folder': folder_name,
                'message': f'Thư mục "{folder_name}" trống'
            })
        
        # Format thông tin files
        files = []
        total_size = 0
        
        for file_item in result:
            file_size = file_item.get('metadata', {}).get('size', 0) or 0
            total_size += file_size
            
            file_info = {
                'name': file_item['name'],
                'full_path': f"{folder_name}/{file_item['name']}",
                'size': file_size,
                'size_human': format_file_size(file_size),
                'content_type': file_item.get('metadata', {}).get('mimetype'),
                'created_at': file_item.get('created_at'),
                'updated_at': file_item.get('updated_at'),
                'public_url': supabase.storage.from_(SUPABASE_BUCKET).get_public_url(f"{folder_name}/{file_item['name']}")
            }
            files.append(file_info)
        
        # Sắp xếp theo tên
        files.sort(key=lambda x: x['name'])
        
        return jsonify({
            'success': True,
            'files': files,
            'count': len(files),
            'folder': folder_name,
            'total_size': total_size,
            'total_size_human': format_file_size(total_size),
            'message': f'Tìm thấy {len(files)} file trong thư mục "{folder_name}"'
        })
        
    except Exception as e:
        print(f"Error getting files in folder {folder_name}: {str(e)}")
        return jsonify({
            'success': False,
            'files': [],
            'error': f'Lỗi đọc thư mục: {str(e)}'
        }), 500

@app.route('/api/folders/init-default', methods=['POST'])
def init_default_folders():
    """Tạo các thư mục mặc định"""
    try:
        default_folders = [
            'Đề tài nghiên cứu',
            'Báo cáo thực tập',
            'Luận văn tốt nghiệp',
            'Tài liệu tham khảo',
            'Hình ảnh minh họa'
        ]
        
        created_folders = []
        errors = []
        
        for folder_name in default_folders:
            try:
                # Tạo README cho mỗi thư mục
                readme_content = f"""# {folder_name}

Thư mục dành cho: {folder_name}
Được tạo tự động vào: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}

## Hướng dẫn sử dụng
1. Upload file thông qua form
2. Chọn thư mục "{folder_name}"
3. Điền đầy đủ thông tin

## Loại file phù hợp
- PDF, DOC, DOCX: Tài liệu chính
- JPG, PNG: Hình ảnh minh họa
- ZIP, RAR: File nén chứa nhiều tài liệu
"""
                
                readme_path = f"{folder_name}/README.md"
                
                # Upload README
                result = supabase.storage.from_(SUPABASE_BUCKET).upload(
                    path=readme_path,
                    file=readme_content.encode('utf-8'),
                    file_options={
                        "content-type": "text/markdown; charset=utf-8"
                    }
                )
                
                if result.status_code == 200:
                    created_folders.append(folder_name)
                    
                    # Lưu vào database
                    try:
                        supabase.table('submissions').insert({
                            'ho_ten': 'System',
                            'ten_de_tai': f'Khởi tạo thư mục: {folder_name}',
                            'noi_cong_tac': 'System',
                            'khoa_phong': 'Administration',
                            'gio_quy_doi': 0,
                            'minh_chung': 'Default Folder Creation',
                            'ghi_chu': f'Thư mục mặc định "{folder_name}" được tạo tự động',
                            'file_name': 'README.md',
                            'file_url': supabase.storage.from_(SUPABASE_BUCKET).get_public_url(readme_path),
                            'file_size': len(readme_content.encode('utf-8')),
                            'folder_name': folder_name,
                            'upload_time': datetime.datetime.now().isoformat(),
                            'upload_ip': get_client_ip(),
                            'storage_path': readme_path
                        }).execute()
                    except Exception as db_error:
                        print(f"DB error for {folder_name}: {str(db_error)}")
                        
                else:
                    errors.append(f"{folder_name}: {result.status_code}")
                    
            except Exception as folder_error:
                errors.append(f"{folder_name}: {str(folder_error)}")
        
        return jsonify({
            'success': True,
            'message': f'Đã tạo {len(created_folders)} thư mục mặc định',
            'created_folders': created_folders,
            'errors': errors,
            'created_count': len(created_folders),
            'error_count': len(errors)
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Lỗi khởi tạo thư mục: {str(e)}'
        }), 500


def create_default_folders_on_startup():
    """Tạo thư mục mặc định khi khởi động server"""
    try:
        # Chờ một chút để server sẵn sàng
        import time
        import threading
        import requests
        
        def delayed_init():
            time.sleep(2)  # Chờ server khởi động
            try:
                response = requests.post('http://localhost:5000/api/folders/init-default')
                print(f"✅ Khởi tạo thư mục mặc định: {response.json()}")
            except Exception as e:
                print(f"❌ Lỗi khởi tạo thư mục: {e}")
        
        # Chạy trong thread riêng
        threading.Thread(target=delayed_init, daemon=True).start()
    except Exception as e:
        print(f"Lỗi setup auto-init: {e}")
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))