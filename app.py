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

def secure_folder_name(folder_name):
    """
    Chuyển đổi tên thư mục thành format an toàn cho Supabase Storage
    """
    if not folder_name or not isinstance(folder_name, str):
        return None
    
    # Bước 1: Loại bỏ khoảng trắng đầu/cuối
    folder_name = folder_name.strip()
    
    if not folder_name:
        return None
    
    # Bước 2: Chuyển đổi tiếng Việt có dấu thành không dấu
    vietnamese_map = {
        'à': 'a', 'á': 'a', 'ả': 'a', 'ã': 'a', 'ạ': 'a',
        'ă': 'a', 'ằ': 'a', 'ắ': 'a', 'ẳ': 'a', 'ẵ': 'a', 'ặ': 'a',
        'â': 'a', 'ầ': 'a', 'ấ': 'a', 'ẩ': 'a', 'ẫ': 'a', 'ậ': 'a',
        'è': 'e', 'é': 'e', 'ẻ': 'e', 'ẽ': 'e', 'ẹ': 'e',
        'ê': 'e', 'ề': 'e', 'ế': 'e', 'ể': 'e', 'ễ': 'e', 'ệ': 'e',
        'ì': 'i', 'í': 'i', 'ỉ': 'i', 'ĩ': 'i', 'ị': 'i',
        'ò': 'o', 'ó': 'o', 'ỏ': 'o', 'õ': 'o', 'ọ': 'o',
        'ô': 'o', 'ồ': 'o', 'ố': 'o', 'ổ': 'o', 'ỗ': 'o', 'ộ': 'o',
        'ơ': 'o', 'ờ': 'o', 'ớ': 'o', 'ở': 'o', 'ỡ': 'o', 'ợ': 'o',
        'ù': 'u', 'ú': 'u', 'ủ': 'u', 'ũ': 'u', 'ụ': 'u',
        'ư': 'u', 'ừ': 'u', 'ứ': 'u', 'ử': 'u', 'ữ': 'u', 'ự': 'u',
        'ỳ': 'y', 'ý': 'y', 'ỷ': 'y', 'ỹ': 'y', 'ỵ': 'y',
        'đ': 'd',
        # Viết hoa
        'À': 'A', 'Á': 'A', 'Ả': 'A', 'Ã': 'A', 'Ạ': 'A',
        'Ă': 'A', 'Ằ': 'A', 'Ắ': 'A', 'Ẳ': 'A', 'Ẵ': 'A', 'Ặ': 'A',
        'Â': 'A', 'Ầ': 'A', 'Ấ': 'A', 'Ẩ': 'A', 'Ẫ': 'A', 'Ậ': 'A',
        'È': 'E', 'É': 'E', 'Ẻ': 'E', 'Ẽ': 'E', 'Ẹ': 'E',
        'Ê': 'E', 'Ề': 'E', 'Ế': 'E', 'Ể': 'E', 'Ễ': 'E', 'Ệ': 'E',
        'Ì': 'I', 'Í': 'I', 'Ỉ': 'I', 'Ĩ': 'I', 'Ị': 'I',
        'Ò': 'O', 'Ó': 'O', 'Ỏ': 'O', 'Õ': 'O', 'Ọ': 'O',
        'Ô': 'O', 'Ồ': 'O', 'Ố': 'O', 'Ổ': 'O', 'Ỗ': 'O', 'Ộ': 'O',
        'Ơ': 'O', 'Ờ': 'O', 'Ớ': 'O', 'Ở': 'O', 'Ỡ': 'O', 'Ợ': 'O',
        'Ù': 'U', 'Ú': 'U', 'Ủ': 'U', 'Ũ': 'U', 'Ụ': 'U',
        'Ư': 'U', 'Ừ': 'U', 'Ứ': 'U', 'Ử': 'U', 'Ữ': 'U', 'Ự': 'U',
        'Ỳ': 'Y', 'Ý': 'Y', 'Ỷ': 'Y', 'Ỹ': 'Y', 'Ỵ': 'Y',
        'Đ': 'D'
    }
    
    # Thay thế ký tự tiếng Việt
    result = ''
    for char in folder_name:
        if char in vietnamese_map:
            result += vietnamese_map[char]
        else:
            result += char
    
    # Bước 3: Thay thế khoảng trắng và ký tự đặc biệt bằng dấu gạch ngang
    result = re.sub(r'[\s\-]+', '-', result)  # Khoảng trắng và dấu gạch ngang
    result = re.sub(r'[^\w\-]', '', result)   # Loại bỏ ký tự đặc biệt khác
    
    # Bước 4: Loại bỏ dấu gạch ngang ở đầu và cuối
    result = result.strip('-')
    
    # Bước 5: Giới hạn độ dài (tùy chọn)
    if len(result) > 50:
        result = result[:50].rstrip('-')
    
    # Bước 6: Kiểm tra kết quả cuối cùng
    if not result or result.isspace():
        return None
    
    return result

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
    if DEMO_MODE:
        # Mô phỏng upload thành công
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_id = str(uuid.uuid4())[:8]
        original_name = secure_filename(file.filename)
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
            'file_size': 1024  # Giả lập 1KB
        }
    
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
                'upload_time': datetime.datetime.now().isoformat(),
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

@app.route('/submissions')
def list_submissions():
    """API để lấy danh sách submissions"""
    if DEMO_MODE:
        return jsonify({
            'submissions': [
                {
                    'id': 1,
                    'ho_ten': 'Demo User',
                    'ten_de_tai': 'Demo Project',
                    'upload_time': datetime.datetime.now().isoformat(),
                    'file_name': 'demo_file.pdf',
                    'file_size': 1024
                }
            ],
            'count': 1,
            'demo_mode': True
        })
    
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
    if DEMO_MODE:
        # Tạo file demo để download
        demo_content = f"Demo file content for submission {submission_id}\nGenerated at: {datetime.datetime.now()}"
        return send_file(
            io.BytesIO(demo_content.encode()),
            as_attachment=True,
            download_name=f"demo_file_{submission_id}.txt",
            mimetype='text/plain'
        )
    
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

# Các API khác có thể được thêm tương tự với kiểm tra DEMO_MODE

# Thêm các API này vào file Flask server của bạn

@app.route('/api/folders', methods=['GET'])
def get_all_folders():
    """API để lấy danh sách tất cả folders từ cả Database và Storage"""
    try:
        folders_data = {
            'database_folders': [],
            'storage_folders': [],
            'combined_folders': []
        }
        
        # 1. Lấy folders từ Database (từ submissions)
        try:
            db_result = supabase.table('submissions').select('folder_name').execute()
            
            # Kiểm tra kết quả database
            print(f"Database result: {db_result}")
            
            # Đếm số lượng submissions theo folder
            folder_counts = {}
            if db_result.data:
                for item in db_result.data:
                    folder_name = item.get('folder_name')
                    if folder_name and folder_name.strip():
                        folder_name = folder_name.strip()
                        folder_counts[folder_name] = folder_counts.get(folder_name, 0) + 1
            
            # Format database folders
            for folder_name, count in folder_counts.items():
                folders_data['database_folders'].append({
                    'name': folder_name,
                    'source': 'database',
                    'submission_count': count
                })
                
        except Exception as db_error:
            print(f"Error getting folders from database: {str(db_error)}")
        
        # 2. Lấy folders từ Storage
        try:
            # Thử nhiều cách để lấy dữ liệu từ storage
            print(f"Trying to access bucket: {SUPABASE_BUCKET}")
            
            # Cách 1: List tất cả files
            storage_result = supabase.storage.from_(SUPABASE_BUCKET).list()
            print(f"Storage result: {storage_result}")
            
            if storage_result:
                storage_folders = {}
                
                for file_item in storage_result:
                    print(f"Processing file item: {file_item}")
                    
                    file_name = file_item.get('name', '')
                    
                    # Kiểm tra nếu là folder (không có extension hoặc có dấu /)
                    if '/' in file_name:
                        # File trong subfolder
                        folder_name = file_name.split('/')[0]
                    elif '.' not in file_name:
                        # Có thể là folder
                        folder_name = file_name
                    else:
                        # File ở root level
                        continue
                    
                    if folder_name and folder_name.strip():
                        folder_name = folder_name.strip()
                        
                        if folder_name not in storage_folders:
                            storage_folders[folder_name] = {
                                'name': folder_name,
                                'source': 'storage',
                                'file_count': 0,
                                'total_size': 0,
                                'last_modified': None
                            }
                        
                        # Chỉ đếm nếu là file thực sự (có extension)
                        if '/' in file_name or '.' in file_name:
                            file_size = 0
                            if 'metadata' in file_item and file_item['metadata']:
                                file_size = file_item['metadata'].get('size', 0) or 0
                            
                            storage_folders[folder_name]['file_count'] += 1
                            storage_folders[folder_name]['total_size'] += file_size
                            
                            # Cập nhật thời gian sửa đổi cuối
                            file_updated = file_item.get('updated_at')
                            if file_updated and (not storage_folders[folder_name]['last_modified'] or 
                                               file_updated > storage_folders[folder_name]['last_modified']):
                                storage_folders[folder_name]['last_modified'] = file_updated
                
                folders_data['storage_folders'] = list(storage_folders.values())
                
            # Cách 2: Nếu cách 1 không work, thử list với recursive
            if not folders_data['storage_folders']:
                try:
                    # Thử list với options khác
                    storage_result_alt = supabase.storage.from_(SUPABASE_BUCKET).list(path="", options={"limit": 1000})
                    print(f"Alternative storage result: {storage_result_alt}")
                    
                    if storage_result_alt:
                        for item in storage_result_alt:
                            folder_name = item.get('name', '').strip()
                            if folder_name and folder_name not in [f['name'] for f in folders_data['storage_folders']]:
                                folders_data['storage_folders'].append({
                                    'name': folder_name,
                                    'source': 'storage',
                                    'file_count': 0,
                                    'total_size': 0,
                                    'last_modified': item.get('updated_at')
                                })
                except Exception as alt_error:
                    print(f"Alternative storage method failed: {str(alt_error)}")
                    
        except Exception as storage_error:
            print(f"Error getting folders from storage: {str(storage_error)}")
        
        # 3. Kết hợp và loại bỏ trùng lặp
        all_folder_names = set()
        
        # Thêm từ database
        for folder in folders_data['database_folders']:
            all_folder_names.add(folder['name'])
        
        # Thêm từ storage
        for folder in folders_data['storage_folders']:
            all_folder_names.add(folder['name'])
        
        # Tạo danh sách kết hợp
        for folder_name in sorted(all_folder_names):
            # Tìm thông tin từ database
            db_info = next((f for f in folders_data['database_folders'] if f['name'] == folder_name), None)
            
            # Tìm thông tin từ storage
            storage_info = next((f for f in folders_data['storage_folders'] if f['name'] == folder_name), None)
            
            combined_folder = {
                'name': folder_name,
                'exists_in_database': db_info is not None,
                'exists_in_storage': storage_info is not None,
                'submission_count': db_info['submission_count'] if db_info else 0,
                'file_count': storage_info['file_count'] if storage_info else 0,
                'total_size': storage_info['total_size'] if storage_info else 0,
                'total_size_human': format_file_size(storage_info['total_size']) if storage_info else '0 B',
                'last_modified': storage_info['last_modified'] if storage_info else None,
                'status': 'active' if (db_info and storage_info) else 'partial'
            }
            
            folders_data['combined_folders'].append(combined_folder)
        
        # Debug output
        print(f"Final result - Database folders: {len(folders_data['database_folders'])}")
        print(f"Final result - Storage folders: {len(folders_data['storage_folders'])}")
        print(f"Final result - Combined folders: {len(folders_data['combined_folders'])}")
        
        return jsonify({
            'success': True,
            'data': folders_data,
            'summary': {
                'total_folders': len(folders_data['combined_folders']),
                'database_only': len([f for f in folders_data['combined_folders'] if f['exists_in_database'] and not f['exists_in_storage']]),
                'storage_only': len([f for f in folders_data['combined_folders'] if f['exists_in_storage'] and not f['exists_in_database']]),
                'both_sources': len([f for f in folders_data['combined_folders'] if f['exists_in_database'] and f['exists_in_storage']])
            },
            'message': f'Tìm thấy {len(folders_data["combined_folders"])} folder'
        })
        
    except Exception as e:
        print(f"Error in get_all_folders: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'Lỗi lấy danh sách folder: {str(e)}'
        }), 500

@app.route('/api/folders/simple', methods=['GET'])
def get_folders_simple():
    """API đơn giản để lấy danh sách tên folder (cho dropdown)"""
    try:
        folder_names = set()
        
        # Lấy từ database
        try:
            result = supabase.table('submissions').select('folder_name').execute()
            print(f"Database folders result: {result}")
            
            if result.data:
                for item in result.data:
                    folder_name = item.get('folder_name')
                    if folder_name and folder_name.strip():
                        folder_names.add(folder_name.strip())
        except Exception as db_error:
            print(f"Database error in simple folders: {str(db_error)}")
        
        # Lấy từ storage
        try:
            storage_result = supabase.storage.from_(SUPABASE_BUCKET).list()
            print(f"Storage folders result: {storage_result}")
            
            if storage_result:
                for item in storage_result:
                    folder_name = item.get('name', '').strip()
                    if folder_name:
                        # Nếu có dấu /, lấy phần đầu
                        if '/' in folder_name:
                            folder_name = folder_name.split('/')[0]
                        # Nếu không có extension, có thể là folder
                        if '.' not in folder_name:
                            folder_names.add(folder_name)
        except Exception as storage_error:
            print(f"Storage error in simple folders: {str(storage_error)}")
        
        # Sắp xếp theo alphabet
        sorted_folders = sorted(list(folder_names))
        
        print(f"Final folders list: {sorted_folders}")
        
        return jsonify({
            'success': True,
            'folders': sorted_folders,
            'count': len(sorted_folders)
        })
        
    except Exception as e:
        print(f"Error in get_folders_simple: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'Lỗi lấy danh sách folder: {str(e)}'
        }), 500

# Thêm endpoint debug để kiểm tra storage
@app.route('/api/debug/storage', methods=['GET'])
def debug_storage():
    """Debug endpoint để kiểm tra storage"""
    try:
        print(f"Debugging storage bucket: {SUPABASE_BUCKET}")
        
        # Thử nhiều cách khác nhau
        methods_results = {}
        
        # Method 1: Basic list
        try:
            result1 = supabase.storage.from_(SUPABASE_BUCKET).list()
            methods_results['basic_list'] = {
                'success': True,
                'data': result1,
                'count': len(result1) if result1 else 0
            }
        except Exception as e:
            methods_results['basic_list'] = {
                'success': False,
                'error': str(e)
            }
        
        # Method 2: List with path
        try:
            result2 = supabase.storage.from_(SUPABASE_BUCKET).list(path="")
            methods_results['list_with_path'] = {
                'success': True,
                'data': result2,
                'count': len(result2) if result2 else 0
            }
        except Exception as e:
            methods_results['list_with_path'] = {
                'success': False,
                'error': str(e)
            }
        
        # Method 3: List with options
        try:
            result3 = supabase.storage.from_(SUPABASE_BUCKET).list(path="", options={"limit": 100})
            methods_results['list_with_options'] = {
                'success': True,
                'data': result3,
                'count': len(result3) if result3 else 0
            }
        except Exception as e:
            methods_results['list_with_options'] = {
                'success': False,
                'error': str(e)
            }
        
        return jsonify({
            'success': True,
            'bucket': SUPABASE_BUCKET,
            'methods': methods_results
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/folders/stats', methods=['GET'])
def get_folder_stats():
    """API để lấy thống kê chi tiết về folders"""
    try:
        # Lấy tất cả submissions
        result = supabase.table('submissions').select('*').execute()
        
        folder_stats = {}
        total_submissions = len(result.data)
        
        for submission in result.data:
            folder_name = submission.get('folder_name', 'Không có thư mục')
            
            if folder_name not in folder_stats:
                folder_stats[folder_name] = {
                    'name': folder_name,
                    'submission_count': 0,
                    'total_file_size': 0,
                    'file_count': 0,
                    'last_upload': None,
                    'contributors': set(),
                    'file_types': {}
                }
            
            stats = folder_stats[folder_name]
            stats['submission_count'] += 1
            
            # File size
            file_size = submission.get('file_size', 0) or 0
            if isinstance(file_size, str):
                file_size = int(file_size) if file_size.isdigit() else 0
            stats['total_file_size'] += file_size
            
            # File count
            if submission.get('file_name'):
                stats['file_count'] += 1
                
                # File type
                file_name = submission.get('file_name', '')
                if '.' in file_name:
                    file_ext = file_name.split('.')[-1].lower()
                    stats['file_types'][file_ext] = stats['file_types'].get(file_ext, 0) + 1
            
            # Contributor
            ho_ten = submission.get('ho_ten')
            if ho_ten:
                stats['contributors'].add(ho_ten)
            
            # Last upload
            upload_time = submission.get('upload_time')
            if upload_time and (not stats['last_upload'] or upload_time > stats['last_upload']):
                stats['last_upload'] = upload_time
        
        # Convert sets to lists và format
        formatted_stats = []
        for folder_name, stats in folder_stats.items():
            formatted_stat = {
                'name': folder_name,
                'submission_count': stats['submission_count'],
                'file_count': stats['file_count'],
                'total_file_size': stats['total_file_size'],
                'total_file_size_human': format_file_size(stats['total_file_size']),
                'contributor_count': len(stats['contributors']),
                'contributors': list(stats['contributors']),
                'file_types': stats['file_types'],
                'last_upload': stats['last_upload'],
                'percentage': round((stats['submission_count'] / total_submissions) * 100, 2) if total_submissions > 0 else 0
            }
            formatted_stats.append(formatted_stat)
        
        # Sắp xếp theo số lượng submission
        formatted_stats.sort(key=lambda x: x['submission_count'], reverse=True)
        
        return jsonify({
            'success': True,
            'folder_stats': formatted_stats,
            'summary': {
                'total_folders': len(formatted_stats),
                'total_submissions': total_submissions,
                'folders_with_files': len([f for f in formatted_stats if f['file_count'] > 0]),
                'empty_folders': len([f for f in formatted_stats if f['file_count'] == 0])
            }
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Lỗi lấy thống kê folder: {str(e)}'
        }), 500

@app.route('/api/folders/create-defaults', methods=['POST'])
def create_default_folders_api():
    """API để tạo các thư mục mặc định - Chỉ tạo thư mục trống"""
    try:
        # Lấy danh sách thư mục từ request hoặc sử dụng mặc định
        data = request.get_json() or {}
        
        # Thư mục mặc định tiếng Việt
        default_folders = data.get('folders', [
            'Đề tài nghiên cứu khoa học',
            'Báo cáo thực tập',
            'Luận văn - Luận án',
            'Tài liệu tham khảo',
            'Hình ảnh - Media',
            'Báo cáo dự án',
            'Tài liệu hướng dẫn',
            'Mẫu biểu - Form',
            'Chứng chỉ - Bằng cấp',
            'Tài liệu hành chính'
        ])
        
        created_folders = []
        existing_folders = []
        errors = []
        
        # Kiểm tra folders đã tồn tại
        try:
            existing_files = supabase.storage.from_(SUPABASE_BUCKET).list()
            existing_folder_names = set()
            
            if existing_files:
                for file_item in existing_files:
                    if '/' in file_item['name']:
                        folder_name = file_item['name'].split('/')[0]
                        existing_folder_names.add(folder_name)
        except Exception as check_error:
            print(f"Error checking existing folders: {str(check_error)}")
            existing_folder_names = set()
        
        # Tạo từng thư mục
        for folder_name in default_folders:
            try:
                safe_folder_name = secure_folder_name(folder_name)
                
                if not safe_folder_name:
                    errors.append(f"{folder_name}: Tên không hợp lệ")
                    continue
                
                if safe_folder_name in existing_folder_names:
                    existing_folders.append(safe_folder_name)
                    continue
                
                # Tạo file trống để tạo thư mục (vì storage cần ít nhất 1 file)
                placeholder_path = f"{safe_folder_name}/.gitkeep"
                
                try:
                    # Upload file trống để tạo thư mục
                    upload_result = supabase.storage.from_(SUPABASE_BUCKET).upload(
                        placeholder_path,
                        b'',  # File trống
                        {
                            'content-type': 'text/plain',
                            'upsert': 'false'
                        }
                    )
                    
                    if upload_result:
                        created_folders.append(safe_folder_name)
                    else:
                        errors.append(f"{safe_folder_name}: Không thể tạo thư mục")
                        
                except Exception as upload_error:
                    error_msg = str(upload_error)
                    if "already exists" in error_msg.lower():
                        existing_folders.append(safe_folder_name)
                    else:
                        errors.append(f"{safe_folder_name}: {error_msg}")
                        
            except Exception as folder_error:
                errors.append(f"{folder_name}: {str(folder_error)}")
        
        # Tạo response
        response_data = {
            'success': True,
            'message': f'Hoàn thành khởi tạo thư mục mặc định',
            'results': {
                'created': {
                    'folders': created_folders,
                    'count': len(created_folders)
                },
                'existing': {
                    'folders': existing_folders,
                    'count': len(existing_folders)
                },
                'errors': {
                    'details': errors,
                    'count': len(errors)
                }
            },
            'summary': {
                'total_requested': len(default_folders),
                'successfully_created': len(created_folders),
                'already_existed': len(existing_folders),
                'failed': len(errors)
            }
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        print(f"Error in create_default_folders_api: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Lỗi tạo thư mục mặc định: {str(e)}'
        }), 500

@app.route('/api/folders/cleanup', methods=['POST'])
def cleanup_empty_folders():
    """API để dọn dẹp các thư mục trống (chỉ có README)"""
    try:
        data = request.get_json() or {}
        confirm = data.get('confirm', False)
        
        if not confirm:
            return jsonify({
                'success': False,
                'error': 'Vui lòng xác nhận việc dọn dẹp bằng cách gửi {"confirm": true}'
            }), 400
        
        # Lấy tất cả files từ storage
        files = supabase.storage.from_(SUPABASE_BUCKET).list()
        
        if not files:
            return jsonify({
                'success': True,
                'message': 'Storage trống, không có gì để dọn dẹp',
                'cleaned_folders': []
            })
        
        # Nhóm files theo thư mục
        folders = {}
        for file_item in files:
            if '/' in file_item['name']:
                folder_name = file_item['name'].split('/')[0]
                if folder_name not in folders:
                    folders[folder_name] = []
                folders[folder_name].append(file_item['name'])
        
        # Tìm thư mục chỉ có README
        empty_folders = []
        for folder_name, file_list in folders.items():
            if len(file_list) == 1 and file_list[0].endswith('/README.md'):
                empty_folders.append(folder_name)
        
        # Xóa các thư mục trống
        cleaned_folders = []
        errors = []
        
        for folder_name in empty_folders:
            try:
                # Xóa README file
                readme_path = f"{folder_name}/README.md"
                delete_result = supabase.storage.from_(SUPABASE_BUCKET).remove([readme_path])
                
                if delete_result:
                    cleaned_folders.append(folder_name)
                    
                    # Xóa record trong database nếu có
                    try:
                        supabase.table('submissions').delete().eq('storage_path', readme_path).execute()
                    except Exception as db_error:
                        print(f"Error removing DB record for {folder_name}: {str(db_error)}")
                        
                else:
                    errors.append(f"{folder_name}: Không thể xóa")
                    
            except Exception as delete_error:
                errors.append(f"{folder_name}: {str(delete_error)}")
        
        return jsonify({
            'success': True,
            'message': f'Đã dọn dẹp {len(cleaned_folders)} thư mục trống',
            'cleaned_folders': cleaned_folders,
            'errors': errors,
            'total_cleaned': len(cleaned_folders),
            'total_errors': len(errors)
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Lỗi dọn dẹp thư mục: {str(e)}'
        }), 500
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))