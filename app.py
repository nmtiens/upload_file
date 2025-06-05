from email import charset
import mimetypes
import re
from flask import Flask, request, render_template, jsonify, send_file
import os
from urllib.parse import unquote
import datetime
from werkzeug.utils import secure_filename
import sqlite3
import shutil
import math
from pathlib import Path
import platform

app = Flask(__name__)

# Cấu hình đường dẫn lưu trữ linh hoạt
def get_storage_path():
    """Xác định đường dẫn lưu trữ file dựa trên hệ điều hành và cấu hình"""
    
    # Kiểm tra biến môi trường trước
    if 'UPLOAD_PATH' in os.environ:
        custom_path = os.environ['UPLOAD_PATH']
        if os.path.isabs(custom_path):
            return custom_path
    
    # Lấy thư mục home của user hiện tại
    home_dir = Path.home()
    
    # Tạo thư mục uploads trong home directory
    if platform.system() == "Windows":
        uploads_dir = home_dir / "Documents" / "FileManager_Uploads"
    else:
        uploads_dir = home_dir / "FileManager_Uploads"
    
    # Tạo thư mục nếu chưa có
    uploads_dir.mkdir(parents=True, exist_ok=True)
    
    return str(uploads_dir)

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
app.config['UPLOAD_FOLDER'] = get_storage_path()
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# In thông tin đường dẫn lưu trữ khi khởi động
print(f"=== FILE UPLOAD SERVER ===")
print(f"Storage Path: {app.config['UPLOAD_FOLDER']}")
print(f"Server sẽ lưu tất cả file upload vào: {app.config['UPLOAD_FOLDER']}")
print("=" * 50)

# Đảm bảo thư mục uploads tồn tại
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Đường dẫn database trong cùng thư mục với uploads
DB_PATH = os.path.join(app.config['UPLOAD_FOLDER'], 'submissions.db')

def init_db():
    """Khởi tạo database trong thư mục uploads"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ho_ten TEXT NOT NULL,
            noi_cong_tac TEXT NOT NULL,
            khoa_phong TEXT,
            ten_de_tai TEXT NOT NULL,
            gio_quy_doi REAL DEFAULT 0,
            minh_chung TEXT,
            ghi_chu TEXT,
            file_name TEXT,
            file_path TEXT,
            file_size INTEGER DEFAULT 0,
            folder_name TEXT,
            upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            upload_ip TEXT,
            server_path TEXT
        )
    ''')
    
    # Thêm cột mới nếu chưa có (cho version cũ)
    try:
        cursor.execute('ALTER TABLE submissions ADD COLUMN upload_ip TEXT')
    except sqlite3.OperationalError:
        pass  # Cột đã tồn tại
    
    try:
        cursor.execute('ALTER TABLE submissions ADD COLUMN server_path TEXT')
    except sqlite3.OperationalError:
        pass  # Cột đã tồn tại
        
    try:
        cursor.execute('ALTER TABLE submissions ADD COLUMN khoa_phong TEXT')
    except sqlite3.OperationalError:
        pass  # Cột đã tồn tại
    
    conn.commit()
    conn.close()
    print(f"Database initialized at: {DB_PATH}")


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

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/info')
def server_info():
    """API để lấy thông tin server"""
    return jsonify({
        'storage_path': app.config['UPLOAD_FOLDER'],
        'database_path': DB_PATH,
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
        noi_cong_tac = request.form.get('noi_cong_tac', '').strip()  # Không bắt buộc
        khoa_phong = request.form.get('khoa_phong', '').strip()
        gio_quy_doi = request.form.get('gio_quy_doi', '0')
        minh_chung = request.form.get('minh_chung', '').strip()
        ghi_chu = request.form.get('ghi_chu', '').strip()
        folder_name = request.form.get('folder', '').strip()

        # Chỉ kiểm tra họ tên và tên đề tài (bỏ nơi công tác)
        if not all([ho_ten, ten_de_tai]):
            return jsonify({'error': 'Vui lòng điền đầy đủ họ tên và tên đề tài'}), 400

        try:
            gio_quy_doi = float(gio_quy_doi)
        except ValueError:
            gio_quy_doi = 0.0

        file_path = None
        final_folder_name = None
        absolute_server_path = app.config['UPLOAD_FOLDER']

        # CHỈ xử lý thư mục khi có folder_name từ form
        if folder_name:
            # Sử dụng hàm tùy chỉnh thay vì secure_filename
            safe_folder_name = secure_folder_name(folder_name)
            if not safe_folder_name:
                return jsonify({'error': 'Tên thư mục không hợp lệ'}), 400
                
            folder_path = os.path.join(app.config['UPLOAD_FOLDER'], safe_folder_name)

            # Chặn truy cập vượt cấp
            if not os.path.abspath(folder_path).startswith(os.path.abspath(app.config['UPLOAD_FOLDER'])):
                return jsonify({'error': 'Tên thư mục không hợp lệ'}), 400

            # Tạo thư mục nếu chưa có
            os.makedirs(folder_path, exist_ok=True)
            final_folder_name = safe_folder_name
            absolute_server_path = folder_path
        else:
            # Không có folder được chỉ định -> lưu trực tiếp vào thư mục gốc
            folder_path = app.config['UPLOAD_FOLDER']

        file_name = None
        file_size = 0
        if 'file' in request.files:
            file = request.files['file']
            if file and hasattr(file, 'filename') and file.filename and file.filename.strip():
                if allowed_file(file.filename):
                    original_name = secure_filename(file.filename)  # Vẫn dùng secure_filename cho tên file
                    if original_name:
                        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                        name, ext = os.path.splitext(original_name)
                        file_name = f"{name}_{timestamp}{ext}"
                        file_path = os.path.join(folder_path, file_name)
                        
                        # Lưu file
                        file.save(file_path)
                        
                        try:
                            file_size = os.path.getsize(file_path)
                        except OSError:
                            file_size = 0
                        
                        print(f"File saved: {file_path} ({format_file_size(file_size)}) from IP: {client_ip}")
                    else:
                        return jsonify({'error': 'Tên file không hợp lệ'}), 400
                else:
                    return jsonify({'error': 'Loại file không được hỗ trợ'}), 400

        # Lưu vào database
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO submissions 
            (ho_ten, ten_de_tai, noi_cong_tac, khoa_phong, gio_quy_doi, minh_chung, ghi_chu, 
             file_name, file_path, file_size, folder_name, upload_time, upload_ip, server_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (ho_ten, ten_de_tai, noi_cong_tac, khoa_phong, gio_quy_doi, minh_chung, ghi_chu,
              file_name, file_path, file_size, final_folder_name, 
              datetime.datetime.now().isoformat(), client_ip, absolute_server_path))
        conn.commit()
        conn.close()

        # Tạo message phản hồi
        if final_folder_name:
            message = f'Đã upload thành công vào thư mục "{final_folder_name}"'
        else:
            message = 'Upload thành công vào thư mục gốc!'
        
        message += f' - Lưu tại: {absolute_server_path}'

        return jsonify({
            'message': message,
            'file_name': file_name,
            'file_size': file_size,
            'file_size_human': format_file_size(file_size),
            'folder': final_folder_name,
            'server_path': absolute_server_path,
            'client_ip': client_ip
        })

    except Exception as e:
        print(f"Upload error: {str(e)}")
        return jsonify({'error': f'Lỗi: {str(e)}'}), 500

@app.route('/api/validate-folder', methods=['POST'])
def validate_folder():
    """API để validate tên thư mục trước khi upload"""
    try:
        data = request.get_json()
        if not data or 'folder_name' not in data:
            return jsonify({'valid': False, 'error': 'Thiếu tên thư mục'}), 400
        
        folder_name = data['folder_name'].strip()
        if not folder_name:
            return jsonify({'valid': False, 'error': 'Tên thư mục không được để trống'}), 400
        
        # Sử dụng hàm tùy chỉnh thay vì secure_filename
        safe_folder_name = secure_folder_name(folder_name)
        if not safe_folder_name:
            return jsonify({'valid': False, 'error': 'Tên thư mục chứa ký tự không hợp lệ'}), 400
        
        # Kiểm tra thư mục đã tồn tại chưa
        folder_path = os.path.join(app.config['UPLOAD_FOLDER'], safe_folder_name)
        folder_exists = os.path.exists(folder_path)
        
        return jsonify({
            'valid': True,
            'folder_name': safe_folder_name,
            'exists': folder_exists,
            'full_path': folder_path,
            'original_name': folder_name,
            'changed': folder_name != safe_folder_name  # Thông báo nếu tên bị thay đổi
        })
        
    except Exception as e:
        return jsonify({'valid': False, 'error': f'Lỗi validate: {str(e)}'}), 500
    
@app.route('/api/cleanup-folders', methods=['POST'])
def cleanup_folders():
    """API để dọn dẹp các thư mục trống hoặc không mong muốn"""
    try:
        data = request.get_json() or {}
        dry_run = data.get('dry_run', True)  # Mặc định chỉ xem trước, không xóa
        
        empty_folders = []
        suspicious_folders = []
        
        upload_path = app.config['UPLOAD_FOLDER']
        
        for item in os.listdir(upload_path):
            item_path = os.path.join(upload_path, item)
            
            if os.path.isdir(item_path):
                # Kiểm tra thư mục trống
                try:
                    files_in_folder = os.listdir(item_path)
                    if not files_in_folder:
                        empty_folders.append({
                            'name': item,
                            'path': item_path,
                            'reason': 'Thư mục trống'
                        })
                    
                    # Kiểm tra thư mục có tên giống tên người (có thể bị tạo nhầm)
                    # Thư mục tự tạo thường có dấu tiếng Việt được chuyển thành không dấu
                    if any(char in item for char in ['_', '-']) and len(item) > 10:
                        # Có thể là tên người được secure_filename
                        suspicious_folders.append({
                            'name': item,
                            'path': item_path,
                            'file_count': len(files_in_folder),
                            'reason': 'Có thể là thư mục tự tạo từ tên người'
                        })
                        
                except PermissionError:
                    continue
        
        result = {
            'empty_folders': empty_folders,
            'suspicious_folders': suspicious_folders,
            'dry_run': dry_run
        }
        
        # Nếu không phải dry run và có yêu cầu xóa
        if not dry_run and data.get('delete_empty', False):
            deleted_folders = []
            for folder_info in empty_folders:
                try:
                    os.rmdir(folder_info['path'])
                    deleted_folders.append(folder_info['name'])
                except Exception as e:
                    print(f"Cannot delete {folder_info['path']}: {e}")
            
            result['deleted_folders'] = deleted_folders
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'error': f'Lỗi cleanup: {str(e)}'}), 500

@app.route('/api/folders/<folder_name>/rename', methods=['PUT'])
def rename_folder(folder_name):
    """API để đổi tên thư mục"""
    try:
        data = request.get_json()
        if not data or 'new_name' not in data:
            return jsonify({'error': 'Thiếu tên mới'}), 400
        
        new_name = data['new_name'].strip()
        if not new_name:
            return jsonify({'error': 'Tên mới không được để trống'}), 400
        
        # Validate tên mới
        safe_new_name = secure_filename(new_name)
        if not safe_new_name:
            return jsonify({'error': 'Tên mới không hợp lệ'}), 400
        
        # Đường dẫn cũ và mới
        old_folder_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(folder_name))
        new_folder_path = os.path.join(app.config['UPLOAD_FOLDER'], safe_new_name)
        
        # Kiểm tra thư mục cũ có tồn tại không
        if not os.path.exists(old_folder_path):
            return jsonify({'error': 'Thư mục không tồn tại'}), 404
        
        # Kiểm tra thư mục mới đã tồn tại chưa
        if os.path.exists(new_folder_path):
            return jsonify({'error': f'Thư mục "{safe_new_name}" đã tồn tại'}), 400
        
        # Đổi tên thư mục
        os.rename(old_folder_path, new_folder_path)
        
        # Cập nhật database
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE submissions 
            SET folder_name = ?, server_path = ?
            WHERE folder_name = ?
        ''', (safe_new_name, new_folder_path, folder_name))
        
        # Cập nhật file_path cho các file trong thư mục
        cursor.execute('''
            UPDATE submissions 
            SET file_path = REPLACE(file_path, ?, ?)
            WHERE folder_name = ?
        ''', (old_folder_path, new_folder_path, safe_new_name))
        
        conn.commit()
        updated_rows = cursor.rowcount
        conn.close()
        
        return jsonify({
            'message': f'Đã đổi tên thư mục từ "{folder_name}" thành "{safe_new_name}"',
            'old_name': folder_name,
            'new_name': safe_new_name,
            'updated_submissions': updated_rows
        })
        
    except Exception as e:
        return jsonify({'error': f'Lỗi đổi tên: {str(e)}'}), 500

@app.route('/api/submissions')
def get_submissions():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM submissions ORDER BY upload_time DESC')
        rows = cursor.fetchall()
        conn.close()
        
        submissions = []
        for row in rows:
            file_size = row[10] or 0  # file_size ở vị trí 10 sau khi thêm khoa_phong
            try:
                if isinstance(file_size, str):
                    file_size = int(file_size) if file_size.isdigit() else 0
                file_size_human = format_file_size(file_size)
            except (ValueError, TypeError):
                file_size = 0
                file_size_human = "0 B"
            
            # Kiểm tra file có tồn tại không
            file_exists = False
            if len(row) > 9 and row[9]:  # file_path ở vị trí 9
                file_exists = os.path.exists(row[9])
            
            submission_data = {
                'id': row[0],
                'ho_ten': row[1],
                'noi_cong_tac': row[2],
                'khoa_phong': row[3] if len(row) > 3 else None,
                'ten_de_tai': row[4],
                'gio_quy_doi': row[5],
                'minh_chung': row[6],
                'ghi_chu': row[7],
                'file_name': row[8],
                'filename': row[8],
                'file_path': row[9],
                'file_size': file_size,
                'file_size_human': file_size_human,
                'folder_name': row[11],
                'upload_time': row[12],
                'upload_ip': row[13] if len(row) > 13 else None,
                'server_path': row[14] if len(row) > 14 else None,
                'file_exists': file_exists
            }
            submissions.append(submission_data)
        
        return jsonify(submissions)
    except Exception as e:
        print(f"Error in get_submissions: {str(e)}")
        return jsonify({'error': f'Lỗi: {str(e)}'}), 500

# Các route khác giữ nguyên như code gốc, chỉ thay đổi đường dẫn database
@app.route('/api/submissions/<int:submission_id>', methods=['GET'])
def get_submission(submission_id):
    """Lấy thông tin chi tiết một submission"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM submissions WHERE id = ?', (submission_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return jsonify({'error': 'Không tìm thấy submission'}), 404
        
        file_size = row[10] or 0  # file_size ở vị trí 10
        try:
            if isinstance(file_size, str):
                file_size = int(file_size) if file_size.isdigit() else 0
            file_size_human = format_file_size(file_size)
        except (ValueError, TypeError):
            file_size = 0
            file_size_human = "0 B"
        
        file_exists = False
        if len(row) > 9 and row[9]:  # file_path ở vị trí 9
            file_exists = os.path.exists(row[9])
        
        submission = {
            'id': row[0],
            'ho_ten': row[1],
            'noi_cong_tac': row[2],
            'khoa_phong': row[3] if len(row) > 3 else None,
            'ten_de_tai': row[4],
            'gio_quy_doi': row[5],
            'minh_chung': row[6],
            'ghi_chu': row[7],
            'file_name': row[8],
            'filename': row[8],
            'file_path': row[9],
            'file_size': file_size,
            'file_size_human': file_size_human,
            'folder_name': row[11],
            'upload_time': row[12],
            'upload_ip': row[13] if len(row) > 13 else None,
            'server_path': row[14] if len(row) > 14 else None,
            'file_exists': file_exists
        }
        
        return jsonify(submission)
    except Exception as e:
        return jsonify({'error': f'Lỗi: {str(e)}'}), 500

@app.route('/download/submission/<int:submission_id>')
def download_submission_file(submission_id):
    """Download file theo submission ID"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT file_name, file_path FROM submissions WHERE id = ?', (submission_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return jsonify({'error': 'Không tìm thấy submission'}), 404
        
        file_name, file_path = row
        
        if not file_name or not file_path:
            return jsonify({'error': 'Submission không có file đính kèm'}), 404
        
        if os.path.exists(file_path) and os.path.isfile(file_path):
            print(f"Downloading file: {file_path}")
            return send_file(file_path, as_attachment=True, download_name=file_name)
        
        return jsonify({'error': 'File không tồn tại trên server'}), 404
        
    except Exception as e:
        print(f"Download submission error: {str(e)}")
        return jsonify({'error': f'Lỗi: {str(e)}'}), 500

@app.route('/api/cleanup')
def cleanup_files():
    """API để dọn dẹp file không tồn tại"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT id, file_name, file_path FROM submissions WHERE file_path IS NOT NULL')
        rows = cursor.fetchall()
        
        missing_files = []
        for row in rows:
            submission_id, file_name, file_path = row
            if not os.path.exists(file_path):
                missing_files.append({
                    'id': submission_id,
                    'file_name': file_name,
                    'file_path': file_path
                })
        
        conn.close()
        
        return jsonify({
            'missing_files': missing_files,
            'total_missing': len(missing_files)
        })
    except Exception as e:
        return jsonify({'error': f'Lỗi: {str(e)}'}), 500



@app.route('/api/submissions/<int:submission_id>', methods=['PUT'])
def update_submission(submission_id):
    """Cập nhật thông tin submission"""
    try:
        # Kiểm tra submission có tồn tại không
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT file_name, file_path, file_size FROM submissions WHERE id = ?', (submission_id,))
        existing = cursor.fetchone()
        
        if not existing:
            conn.close()
            return jsonify({'error': 'Không tìm thấy submission'}), 404
        
        old_filename = existing[0]
        old_filepath = existing[1]
        old_filesize = existing[2] or 0
        
        # Lấy dữ liệu từ request
        if request.is_json:
            data = request.get_json()
            ho_ten = data.get('ho_ten', '').strip()
            ten_de_tai = data.get('ten_de_tai', '').strip()
            noi_cong_tac = data.get('noi_cong_tac', '').strip()  # Không bắt buộc
            khoa_phong = data.get('khoa_phong', '').strip()
            gio_quy_doi = data.get('gio_quy_doi', 0)
            minh_chung = data.get('minh_chung', '').strip()
            ghi_chu = data.get('ghi_chu', '').strip()
            new_filename = old_filename
            new_filepath = old_filepath
            new_filesize = old_filesize
        else:
            # Xử lý form data (có thể có file upload)
            ho_ten = request.form.get('ho_ten', '').strip()
            ten_de_tai = request.form.get('ten_de_tai', '').strip()
            noi_cong_tac = request.form.get('noi_cong_tac', '').strip()  # Không bắt buộc
            khoa_phong = request.form.get('khoa_phong', '').strip()
            gio_quy_doi = request.form.get('gio_quy_doi', 0)
            minh_chung = request.form.get('minh_chung', '').strip()
            ghi_chu = request.form.get('ghi_chu', '').strip()
            new_filename = old_filename
            new_filepath = old_filepath
            new_filesize = old_filesize
            
            # Xử lý file upload mới (nếu có)
            if 'file' in request.files:
                file = request.files['file']
                if file and hasattr(file, 'filename') and file.filename and file.filename.strip():
                    if allowed_file(file.filename):
                        # Xóa file cũ nếu có
                        if old_filepath and os.path.exists(old_filepath):
                            os.remove(old_filepath)
                        
                        # Lưu file mới
                        original_name = secure_filename(file.filename)
                        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                        name, ext = os.path.splitext(original_name)
                        new_filename = f"{name}_{timestamp}{ext}"
                        new_filepath = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
                        file.save(new_filepath)
                        
                        try:
                            new_filesize = os.path.getsize(new_filepath)
                        except OSError:
                            new_filesize = 0
        
        # Chỉ kiểm tra họ tên và tên đề tài (bỏ nơi công tác)
        if not all([ho_ten, ten_de_tai]):
            conn.close()
            return jsonify({'error': 'Vui lòng điền đầy đủ họ tên và tên đề tài'}), 400
        
        try:
            gio_quy_doi = float(gio_quy_doi)
        except (ValueError, TypeError):
            gio_quy_doi = 0.0
        
        # Cập nhật database
        cursor.execute('''
            UPDATE submissions 
            SET ho_ten = ?, ten_de_tai = ?, noi_cong_tac = ?, khoa_phong = ?, gio_quy_doi = ?, 
                minh_chung = ?, ghi_chu = ?, file_name = ?, file_path = ?, file_size = ?
            WHERE id = ?
        ''', (ho_ten, ten_de_tai, noi_cong_tac, khoa_phong, gio_quy_doi, minh_chung, ghi_chu, 
              new_filename, new_filepath, new_filesize, submission_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'message': 'Cập nhật thành công!', 
            'id': submission_id,
            'file_size': new_filesize,
            'file_size_human': format_file_size(new_filesize)
        })
    
    except Exception as e:
        return jsonify({'error': f'Lỗi: {str(e)}'}), 500


@app.route('/api/submissions/<int:submission_id>', methods=['DELETE'])
def delete_submission(submission_id):
    """Xóa submission - Fixed version"""
    try:
        conn = sqlite3.connect(DB_PATH)  # Sử dụng DB_PATH thay vì hard-coded
        cursor = conn.cursor()
        
        # Lấy thông tin file để xóa
        cursor.execute('SELECT file_name, file_path FROM submissions WHERE id = ?', (submission_id,))
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return jsonify({'error': 'Không tìm thấy submission'}), 404
        
        filepath = row[1]
        
        # Xóa file khỏi disk nếu có
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
                print(f"Deleted file: {filepath}")
            except Exception as e:
                print(f"Cannot delete file {filepath}: {e}")
        
        # Xóa record khỏi database
        cursor.execute('DELETE FROM submissions WHERE id = ?', (submission_id,))
        conn.commit()
        conn.close()
        
        return jsonify({'message': 'Xóa thành công!', 'id': submission_id})
    
    except Exception as e:
        return jsonify({'error': f'Lỗi: {str(e)}'}), 500

@app.route('/api/folders', methods=['GET'])
def get_folders():
    """Lấy danh sách tất cả thư mục trong uploads - Fixed version"""
    try:
        folders = []
        upload_path = app.config['UPLOAD_FOLDER']
        
        # Tạo thư mục upload nếu chưa có
        if not os.path.exists(upload_path):
            os.makedirs(upload_path, exist_ok=True)
        
        # Lấy danh sách thư mục thực tế trên disk
        for item in os.listdir(upload_path):
            item_path = os.path.join(upload_path, item)
            if os.path.isdir(item_path):
                file_count = 0
                total_size = 0
                try:
                    for file_item in os.listdir(item_path):
                        file_path = os.path.join(item_path, file_item)
                        if os.path.isfile(file_path):
                            file_count += 1
                            total_size += os.path.getsize(file_path)
                except PermissionError:
                    file_count = 0
                    total_size = 0
                
                folders.append({
                    'name': item,
                    'file_count': file_count,
                    'total_size': total_size,
                    'total_size_human': format_file_size(total_size),
                    'created_time': datetime.datetime.fromtimestamp(
                        os.path.getctime(item_path)
                    ).strftime('%Y-%m-%d %H:%M:%S')
                })
        
        folders.sort(key=lambda x: x['name'].lower())
        return jsonify(folders)
    
    except Exception as e:
        return jsonify({'error': f'Không thể lấy danh sách thư mục: {str(e)}'}), 500


@app.route('/api/folders', methods=['POST'])
def create_folder():
    """Tạo thư mục mới"""
    try:
        data = request.get_json()
        if not data or 'name' not in data:
            return jsonify({'error': 'Thiếu tên thư mục'}), 400
        
        folder_name = data['name'].strip()
        if not folder_name:
            return jsonify({'error': 'Tên thư mục không được để trống'}), 400
        
        # Sử dụng hàm tùy chỉnh
        safe_folder_name = secure_folder_name(folder_name)
        if not safe_folder_name:
            return jsonify({'error': 'Tên thư mục không hợp lệ'}), 400
        
        folder_path = os.path.join(app.config['UPLOAD_FOLDER'], safe_folder_name)
        
        if os.path.exists(folder_path):
            return jsonify({'error': 'Thư mục đã tồn tại'}), 400
        
        os.makedirs(folder_path)
        
        return jsonify({
            'message': f'Đã tạo thư mục "{safe_folder_name}" thành công',
            'folder_name': safe_folder_name,
            'original_name': folder_name,
            'changed': folder_name != safe_folder_name
        })
    
    except Exception as e:
        return jsonify({'error': f'Không thể tạo thư mục: {str(e)}'}), 500

@app.route('/api/folders/<folder_name>', methods=['DELETE'])
def delete_folder(folder_name):
    """Xóa thư mục"""
    try:
        folder_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(folder_name))
        
        if not os.path.exists(folder_path):
            return jsonify({'error': 'Thư mục không tồn tại'}), 404
        
        if not os.path.isdir(folder_path):
            return jsonify({'error': 'Đây không phải là thư mục'}), 400
        
        # Xóa thư mục và tất cả nội dung bên trong
        shutil.rmtree(folder_path)
        
        return jsonify({'message': f'Đã xóa thư mục "{folder_name}" thành công'})
    
    except Exception as e:
        return jsonify({'error': f'Không thể xóa thư mục: {str(e)}'}), 500

@app.route('/api/folders/<folder_name>/files', methods=['GET'])
def get_folder_files(folder_name):
    """Lấy danh sách file trong một thư mục cụ thể"""
    try:
        # Kiểm tra thư mục có tồn tại thực tế không
        folder_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(folder_name))
        if not os.path.exists(folder_path) or not os.path.isdir(folder_path):
            return jsonify({'error': 'Thư mục không tồn tại'}), 404
        
        # Lấy danh sách file thực tế trong thư mục
        actual_files = []
        try:
            for item in os.listdir(folder_path):
                item_path = os.path.join(folder_path, item)
                if os.path.isfile(item_path):
                    file_size = os.path.getsize(item_path)
                    file_stat = os.stat(item_path)
                    
                    actual_files.append({
                        'file_name': item,
                        'size': file_size,
                        'size_human': format_file_size(file_size),
                        'upload_time': datetime.datetime.fromtimestamp(file_stat.st_mtime).isoformat(),
                        'exists': True,
                        'file_path': item_path
                    })
        except Exception as e:
            print(f"Error reading folder {folder_name}: {str(e)}")
        
        # Lấy thông tin từ database để bổ sung metadata
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, ho_ten, ten_de_tai, khoa_phong, file_name, gio_quy_doi, upload_time
            FROM submissions 
            WHERE folder_name = ? AND file_name IS NOT NULL AND file_name != ""
            ORDER BY upload_time DESC
        ''', (folder_name,))
        
        db_records = cursor.fetchall()
        conn.close()
        
        # Ghép thông tin từ database với file thực tế
        files = []
        db_files_dict = {record[4]: record for record in db_records}  # file_name -> record
        
        for actual_file in actual_files:
            file_name = actual_file['file_name']
            
            if file_name in db_files_dict:
                # File có trong database
                record = db_files_dict[file_name]
                files.append({
                    'id': record[0],
                    'file_name': file_name,
                    'ho_ten': record[1],
                    'ten_de_tai': record[2],
                    'khoa_phong': record[3],
                    'gio_quy_doi': record[5],
                    'size': actual_file['size'],
                    'size_human': actual_file['size_human'],
                    'upload_time': record[6],
                    'exists': True,
                    'has_metadata': True
                })
            else:
                # File không có trong database
                files.append({
                    'id': None,
                    'file_name': file_name,
                    'ho_ten': 'N/A',
                    'ten_de_tai': 'N/A',
                    'khoa_phong': 'N/A',
                    'gio_quy_doi': 0,
                    'size': actual_file['size'],
                    'size_human': actual_file['size_human'],
                    'upload_time': actual_file['upload_time'],
                    'exists': True,
                    'has_metadata': False
                })
        
        return jsonify({
            'folder_name': folder_name,
            'files': files,
            'total_files': len(files)
        })
    
    except Exception as e:
        return jsonify({'error': f'Không thể lấy danh sách file: {str(e)}'}), 500


@app.route('/api/stats')
def get_stats():
    """Lấy thống kê tổng quan - Fixed version"""
    try:
        conn = sqlite3.connect(DB_PATH)  # Sử dụng DB_PATH thay vì hard-coded
        cursor = conn.cursor()
        
        # Đếm tổng số submissions
        cursor.execute('SELECT COUNT(*) FROM submissions')
        total_submissions = cursor.fetchone()[0]
        
        # Đếm số submissions có file
        cursor.execute('SELECT COUNT(*) FROM submissions WHERE file_name IS NOT NULL AND file_name != ""')
        submissions_with_files = cursor.fetchone()[0]
        
        # Tính tổng kích thước files thực tế trên disk
        total_size = 0
        actual_file_count = 0
        
        if os.path.exists(app.config['UPLOAD_FOLDER']):
            for root, dirs, files in os.walk(app.config['UPLOAD_FOLDER']):
                for file in files:
                    # Bỏ qua file database
                    if file.endswith('.db'):
                        continue
                    file_path = os.path.join(root, file)
                    try:
                        total_size += os.path.getsize(file_path)
                        actual_file_count += 1
                    except:
                        pass
        
        # Đếm thư mục thực tế trên disk
        actual_folders = 0
        if os.path.exists(app.config['UPLOAD_FOLDER']):
            for item in os.listdir(app.config['UPLOAD_FOLDER']):
                item_path = os.path.join(app.config['UPLOAD_FOLDER'], item)
                if os.path.isdir(item_path):
                    actual_folders += 1
        
        conn.close()
        
        return jsonify({
            'total_submissions': total_submissions,
            'submissions_with_files': submissions_with_files,
            'submissions_without_files': total_submissions - submissions_with_files,
            'actual_files_on_disk': actual_file_count,
            'total_file_size': total_size,
            'total_file_size_human': format_file_size(total_size),
            'total_folders_actual': actual_folders
        })
    
    except Exception as e:
        return jsonify({'error': f'Lỗi khi lấy thống kê: {str(e)}'}), 500


@app.route('/api/files/<path:filename>/content', methods=['GET'])
def get_file_content(filename):
    """API để lấy nội dung file - Fixed version"""
    try:
        # URL decode filename để xử lý tên file có ký tự đặc biệt
        decoded_filename = unquote(filename)
        safe_filename = secure_filename(decoded_filename)
        
        if not safe_filename:
            return jsonify({'error': 'Tên file không hợp lệ'}), 400
        
        file_path = None
        
        # Tìm file trong thư mục upload hiện tại
        test_path = os.path.join(app.config['UPLOAD_FOLDER'], safe_filename)
        if os.path.exists(test_path) and os.path.isfile(test_path):
            file_path = test_path
        else:
            # Tìm trong tất cả subfolders của upload hiện tại
            for root, dirs, files in os.walk(app.config['UPLOAD_FOLDER']):
                if safe_filename in files:
                    potential_path = os.path.join(root, safe_filename)
                    if os.path.isfile(potential_path):
                        file_path = potential_path
                        break
        
        if not file_path:
            return jsonify({'error': 'File không tồn tại'}), 404
        
        # Đối với file .doc, .docx, .xls, .xlsx - không thể xem nội dung dạng text
        binary_extensions = ['.doc', '.docx', '.xls', '.xlsx', '.pdf', '.zip', '.rar', '.7z', 
                           '.png', '.jpg', '.jpeg', '.gif', '.mp4', '.mp3', '.exe']
        
        file_ext = os.path.splitext(decoded_filename)[1].lower()
        if file_ext in binary_extensions:
            return jsonify({
                'error': f'File {file_ext} không thể xem nội dung trực tiếp',
                'type': 'binary',
                'extension': file_ext,
                'suggestion': 'Sử dụng chức năng download để tải file này'
            }), 400
        
        # Kiểm tra kích thước file (giới hạn 5MB cho việc xem)
        file_size = os.path.getsize(file_path)
        if file_size > 5 * 1024 * 1024:  # 5MB
            return jsonify({
                'error': 'File quá lớn để xem (>5MB)',
                'size': file_size,
                'size_human': format_file_size(file_size)
            }), 400
        
        # Xác định loại file
        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type:
            mime_type = 'application/octet-stream'
        
        # Kiểm tra xem có phải file text không
        text_types = [
            'text/', 'application/json', 'application/xml', 
            'application/javascript'
        ]
        
        is_text_file = any(mime_type.startswith(t) for t in text_types)
        
        # Thêm kiểm tra extension cho các file code thông dụng
        text_extensions = [
            '.py', '.txt', '.json', '.xml', '.html', '.htm', '.css', '.js', 
            '.csv', '.log', '.md', '.yml', '.yaml', '.ini', '.cfg', '.conf',
            '.sql', '.sh', '.bat', '.ps1', '.dockerfile', '.gitignore'
        ]
        
        if file_ext in text_extensions:
            is_text_file = True
        
        if not is_text_file:
            return jsonify({
                'error': 'File không phải là file text',
                'type': mime_type,
                'extension': file_ext,
                'suggestion': 'Sử dụng chức năng download để tải file này'
            }), 400
        
        # Đọc nội dung file
        try:
            # Thử đọc với UTF-8 trước
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            encoding = 'utf-8'
        except UnicodeDecodeError:
            # Nếu không đọc được UTF-8, thử với các encoding khác
            encodings = ['latin-1', 'cp1252', 'iso-8859-1']
            content = None
            encoding = 'unknown'
            
            for enc in encodings:
                try:
                    with open(file_path, 'r', encoding=enc) as f:
                        content = f.read()
                    encoding = enc
                    break
                except:
                    continue
            
            if content is None:
                return jsonify({'error': 'Không thể đọc file với encoding phù hợp'}), 400
        
        return jsonify({
            'content': content,
            'type': mime_type,
            'encoding': encoding,
            'size': file_size,
            'size_human': format_file_size(file_size),
            'lines': content.count('\n') + 1 if content else 0
        })
        
    except Exception as e:
        print(f"Error reading file {filename}: {str(e)}")
        return jsonify({'error': f'Lỗi đọc file: {str(e)}'}), 500
    
# 2. Fix API download_file - thêm URL decode và xử lý đường dẫn trống
@app.route('/download/')
@app.route('/download/<path:filename>')
def download_file(filename=None):
    """Download file by filename - Fixed version"""
    try:
        if not filename or filename.strip() == '':
            return jsonify({'error': 'Thiếu tên file'}), 400
        
        # URL decode filename để xử lý tên file có ký tự đặc biệt
        decoded_filename = unquote(filename)
        safe_filename = secure_filename(decoded_filename)
        
        if not safe_filename:
            return jsonify({'error': 'Tên file không hợp lệ'}), 400
        
        # Check in current uploads folder first
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], safe_filename)
        
        if os.path.exists(file_path) and os.path.isfile(file_path):
            return send_file(file_path, as_attachment=True, download_name=decoded_filename)
        
        # Search in current upload subfolders
        for root, dirs, files in os.walk(app.config['UPLOAD_FOLDER']):
            if safe_filename in files:
                file_path = os.path.join(root, safe_filename)
                return send_file(file_path, as_attachment=True, download_name=decoded_filename)
        
        return jsonify({'error': 'File không tồn tại'}), 404
        
    except Exception as e:
        print(f"Download error: {str(e)}")
        return jsonify({'error': f'Lỗi: {str(e)}'}), 500



# Additional utility route to check file existence
@app.route('/api/check-file/<int:submission_id>')
def check_file_exists(submission_id):
    """Check if file exists for a submission"""
    try:
        conn = sqlite3.connect('submissions.db')
        cursor = conn.cursor()
        cursor.execute('SELECT file_name, file_path FROM submissions WHERE id = ?', (submission_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return jsonify({'exists': False, 'error': 'Submission not found'})
        
        file_name, file_path = row
        
        if not file_name or not file_path:
            return jsonify({'exists': False, 'error': 'No file attached'})
        
        file_exists = os.path.exists(file_path) and os.path.isfile(file_path)
        
        if not file_exists:
            # Try to find file by name in uploads folder
            safe_filename = secure_filename(file_name)
            for root, dirs, files in os.walk(app.config['UPLOAD_FOLDER']):
                if safe_filename in files:
                    found_path = os.path.join(root, safe_filename)
                    if os.path.isfile(found_path):
                        file_exists = True
                        break
        
        return jsonify({
            'exists': file_exists,
            'file_name': file_name,
            'file_path': file_path
        })
        
    except Exception as e:
        return jsonify({'exists': False, 'error': str(e)})
    
# Thêm API mới để kiểm tra dữ liệu trước khi submit
@app.route('/api/validate-submission', methods=['POST'])
def validate_submission():
    """API để validate dữ liệu submission trước khi upload"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'valid': False, 'error': 'Không có dữ liệu'}), 400
        
        ho_ten = data.get('ho_ten', '').strip()
        ten_de_tai = data.get('ten_de_tai', '').strip()
        noi_cong_tac = data.get('noi_cong_tac', '').strip()
        
        errors = []
        warnings = []
        
        # Kiểm tra bắt buộc
        if not ho_ten:
            errors.append('Họ tên không được để trống')
        
        if not ten_de_tai:
            errors.append('Tên đề tài không được để trống')
        
        # Kiểm tra cảnh báo
        if not noi_cong_tac:
            warnings.append('Nơi công tác chưa được điền')
        
        # Kiểm tra độ dài
        if len(ho_ten) > 100:
            errors.append('Họ tên quá dài (tối đa 100 ký tự)')
        
        if len(ten_de_tai) > 200:
            errors.append('Tên đề tài quá dài (tối đa 200 ký tự)')
        
        if len(noi_cong_tac) > 150:
            errors.append('Nơi công tác quá dài (tối đa 150 ký tự)')
        
        # Kiểm tra giờ quy đổi
        gio_quy_doi = data.get('gio_quy_doi', 0)
        try:
            gio_quy_doi = float(gio_quy_doi)
            if gio_quy_doi < 0:
                errors.append('Giờ quy đổi không được âm')
            elif gio_quy_doi > 1000:
                warnings.append('Giờ quy đổi có vẻ quá lớn')
        except (ValueError, TypeError):
            errors.append('Giờ quy đổi phải là số')
        
        is_valid = len(errors) == 0
        
        return jsonify({
            'valid': is_valid,
            'errors': errors,
            'warnings': warnings,
            'required_fields': ['ho_ten', 'ten_de_tai'],
            'optional_fields': ['noi_cong_tac', 'khoa_phong', 'gio_quy_doi', 'minh_chung', 'ghi_chu']
        })
        
    except Exception as e:
        return jsonify({'valid': False, 'error': f'Lỗi validate: {str(e)}'}), 500
    



# Error handlers
@app.errorhandler(413)
def too_large(e):
    return jsonify({'error': 'File quá lớn (tối đa 16MB)'}), 413

@app.errorhandler(500)
def internal_error(e):
    return jsonify({'error': 'Lỗi server nội bộ'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    
    if os.environ.get('FLASK_ENV') == 'production':
        print(f"🚀 Starting File Upload Server in Production Mode...")
        print(f"🌐 Server running on port: {port}")
        app.run(host='0.0.0.0', port=port, debug=False)
    else:
        print(f"\n🚀 Starting File Upload Server...")
        print(f"📁 Files will be saved to: {app.config['UPLOAD_FOLDER']}")
        print(f"🗄️ Database location: {DB_PATH}")
        print(f"🌐 Server will be available at: http://localhost:5000")
        print(f"🌍 Or from other devices: http://[YOUR_IP]:5000")
        print("\n" + "="*60 + "\n")
        app.run(debug=True, host='0.0.0.0', port=5000)