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
    
# Thêm các API này vào file Flask app của bạn

@app.route('/folders', methods=['GET'])
def list_folders():
    """API để lấy danh sách thư mục trong Supabase Storage"""
    try:
        # Lấy danh sách tất cả files trong bucket
        result = supabase.storage.from_(SUPABASE_BUCKET).list()
        
        if not result:
            return jsonify({
                'folders': [],
                'count': 0,
                'message': 'Không có thư mục nào'
            })
        
        # Tạo set để lưu tên thư mục duy nhất
        folders = set()
        file_count_by_folder = {}
        
        # Duyệt qua tất cả files để tìm thư mục
        for item in result:
            # Nếu item có '/' thì đó là file trong thư mục
            if '/' in item['name']:
                folder_name = item['name'].split('/')[0]
                folders.add(folder_name)
                
                # Đếm số file trong mỗi thư mục
                if folder_name in file_count_by_folder:
                    file_count_by_folder[folder_name] += 1
                else:
                    file_count_by_folder[folder_name] = 1
        
        # Chuyển đổi thành list và thêm thông tin
        folder_list = []
        for folder in sorted(folders):
            folder_info = {
                'name': folder,
                'file_count': file_count_by_folder.get(folder, 0),
                'path': folder
            }
            folder_list.append(folder_info)
        
        return jsonify({
            'folders': folder_list,
            'count': len(folder_list),
            'message': f'Tìm thấy {len(folder_list)} thư mục'
        })
        
    except Exception as e:
        print(f"Error listing folders: {str(e)}")
        return jsonify({
            'error': f'Lỗi khi lấy danh sách thư mục: {str(e)}',
            'folders': [],
            'count': 0
        }), 500


@app.route('/api/folders', methods=['GET'])
def get_folders_simple():
    """API đơn giản để lấy danh sách thư mục cho trang web"""
    try:
        # Lấy từ database submissions thay vì storage để nhanh hơn
        result = supabase.table('submissions').select('folder_name').execute()
        
        if not result.data:
            return jsonify({
                'success': True,
                'folders': [],
                'message': 'Chưa có thư mục nào'
            })
        
        # Lấy danh sách folder_name duy nhất và không null
        folders = set()
        for item in result.data:
            folder_name = item.get('folder_name')
            if folder_name and folder_name.strip():
                folders.add(folder_name.strip())
        
        # Chuyển thành list và sắp xếp
        folder_list = sorted(list(folders))
        
        return jsonify({
            'success': True,
            'folders': folder_list,
            'count': len(folder_list)
        })
        
    except Exception as e:
        print(f"Error getting folders: {str(e)}")
        return jsonify({
            'success': False,
            'folders': [],
            'error': str(e)
        }), 500
        
        
@app.route('/folders/<path:folder_path>/files', methods=['GET'])
def list_files_in_folder(folder_path):
    """API để lấy danh sách files trong một thư mục cụ thể"""
    try:
        # Giải mã folder_path nếu có ký tự đặc biệt
        folder_path = unquote(folder_path)
        
        # Lấy danh sách files trong thư mục
        result = supabase.storage.from_(SUPABASE_BUCKET).list(folder_path)
        
        if not result:
            return jsonify({
                'files': [],
                'count': 0,
                'folder': folder_path,
                'message': f'Thư mục "{folder_path}" trống hoặc không tồn tại'
            })
        
        # Chuyển đổi thông tin files
        files = []
        for item in result:
            file_info = {
                'name': item['name'],
                'size': item.get('metadata', {}).get('size', 0),
                'size_human': format_file_size(item.get('metadata', {}).get('size', 0)),
                'created_at': item.get('created_at'),
                'updated_at': item.get('updated_at'),
                'content_type': item.get('metadata', {}).get('mimetype'),
                'full_path': f"{folder_path}/{item['name']}"
            }
            files.append(file_info)
        
        return jsonify({
            'files': files,
            'count': len(files),
            'folder': folder_path,
            'message': f'Tìm thấy {len(files)} file trong thư mục "{folder_path}"'
        })
        
    except Exception as e:
        print(f"Error listing files in folder {folder_path}: {str(e)}")
        return jsonify({
            'error': f'Lỗi khi lấy files trong thư mục: {str(e)}',
            'files': [],
            'count': 0,
            'folder': folder_path
        }), 500

@app.route('/folders', methods=['POST'])
def create_folder():
    """API để tạo thư mục mới trong Supabase Storage"""
    try:
        data = request.get_json()
        
        if not data or 'folder_name' not in data:
            return jsonify({'error': 'Vui lòng cung cấp tên thư mục'}), 400
        
        folder_name = data['folder_name'].strip()
        
        if not folder_name:
            return jsonify({'error': 'Tên thư mục không được để trống'}), 400
        
        # Làm sạch tên thư mục
        safe_folder_name = secure_folder_name(folder_name)
        
        if not safe_folder_name:
            return jsonify({'error': 'Tên thư mục không hợp lệ'}), 400
        
        # Kiểm tra xem thư mục đã tồn tại chưa
        existing_folders = supabase.storage.from_(SUPABASE_BUCKET).list()
        
        if existing_folders:
            for item in existing_folders:
                if '/' in item['name'] and item['name'].split('/')[0] == safe_folder_name:
                    return jsonify({
                        'error': f'Thư mục "{safe_folder_name}" đã tồn tại',
                        'folder_name': safe_folder_name
                    }), 400
        
        # Tạo file placeholder để tạo thư mục (vì Supabase Storage cần ít nhất 1 file)
        placeholder_content = f"Thư mục được tạo vào {datetime.datetime.now().isoformat()}"
        placeholder_path = f"{safe_folder_name}/.folder_created"
        
        # Upload file placeholder
        result = supabase.storage.from_(SUPABASE_BUCKET).upload(
            path=placeholder_path,
            file=placeholder_content.encode('utf-8'),
            file_options={
                "content-type": "text/plain"
            }
        )
        
        if result.status_code == 200:
            # Lưu thông tin tạo thư mục vào database
            try:
                client_ip = get_client_ip()
                supabase.table('submissions').insert({
                    'ho_ten': 'System',
                    'ten_de_tai': f'Tạo thư mục: {safe_folder_name}',
                    'noi_cong_tac': '',
                    'khoa_phong': '',
                    'gio_quy_doi': 0,
                    'minh_chung': 'Folder creation',
                    'ghi_chu': f'Thư mục được tạo tự động',
                    'file_name': '.folder_created',
                    'file_url': supabase.storage.from_(SUPABASE_BUCKET).get_public_url(placeholder_path),
                    'file_size': len(placeholder_content.encode('utf-8')),
                    'folder_name': safe_folder_name,
                    'upload_time': datetime.datetime.now().isoformat(),
                    'upload_ip': client_ip,
                    'storage_path': placeholder_path
                }).execute()
            except Exception as db_error:
                print(f"Database logging error for folder creation: {str(db_error)}")
            
            return jsonify({
                'message': f'Thư mục "{safe_folder_name}" đã được tạo thành công',
                'folder_name': safe_folder_name,
                'folder_path': safe_folder_name,
                'placeholder_file': placeholder_path
            })
        else:
            return jsonify({
                'error': f'Không thể tạo thư mục: {result.status_code}'
            }), 500
            
    except Exception as e:
        print(f"Error creating folder: {str(e)}")
        return jsonify({'error': f'Lỗi khi tạo thư mục: {str(e)}'}), 500

@app.route('/folders/<path:folder_path>', methods=['DELETE'])
def delete_folder(folder_path):
    """API để xóa thư mục và tất cả files trong đó"""
    try:
        folder_path = unquote(folder_path)
        
        if not folder_path:
            return jsonify({'error': 'Tên thư mục không hợp lệ'}), 400
        
        # Lấy danh sách tất cả files trong thư mục
        files_in_folder = supabase.storage.from_(SUPABASE_BUCKET).list(folder_path)
        
        if not files_in_folder:
            return jsonify({'error': f'Thư mục "{folder_path}" không tồn tại hoặc đã trống'}), 404
        
        # Xóa từng file trong thư mục
        deleted_files = []
        errors = []
        
        for file_item in files_in_folder:
            file_path = f"{folder_path}/{file_item['name']}"
            try:
                result = supabase.storage.from_(SUPABASE_BUCKET).remove([file_path])
                if result:
                    deleted_files.append(file_path)
                else:
                    errors.append(f"Không thể xóa {file_path}")
            except Exception as e:
                errors.append(f"Lỗi xóa {file_path}: {str(e)}")
        
        # Cập nhật database - đánh dấu các submissions liên quan
        try:
            supabase.table('submissions').update({
                'ghi_chu': f"Thư mục đã bị xóa vào {datetime.datetime.now().isoformat()}"
            }).eq('folder_name', folder_path).execute()
        except Exception as db_error:
            print(f"Database update error for folder deletion: {str(db_error)}")
        
        if errors:
            return jsonify({
                'message': f'Xóa thư mục "{folder_path}" hoàn tất với một số lỗi',
                'deleted_files': deleted_files,
                'errors': errors,
                'deleted_count': len(deleted_files),
                'error_count': len(errors)
            }), 207  # Multi-status
        else:
            return jsonify({
                'message': f'Xóa thư mục "{folder_path}" thành công',
                'deleted_files': deleted_files,
                'deleted_count': len(deleted_files)
            })
            
    except Exception as e:
        print(f"Error deleting folder {folder_path}: {str(e)}")
        return jsonify({'error': f'Lỗi khi xóa thư mục: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))