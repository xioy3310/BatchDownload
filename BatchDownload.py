import os
import sys
import time
import argparse
import asyncio
import aiohttp
from aiohttp import ClientError, ClientTimeout
from pathlib import Path
import traceback

# 失败链接文件
ERROR_FILE = "error.txt"

# 全局统计变量
total_count = 0
success_count = 0
fail_count = 0
failed_urls = []

async def download_file(session, url, retry_times, timeout, save_dir):
    """
    下载单个文件
    """
    global success_count, fail_count
    filename = None
    
    for attempt in range(retry_times + 1):
        try:
            async with session.get(url, timeout=timeout) as response:
                if response.status != 200:
                    raise ClientError(f"HTTP状态码: {response.status}")
                
                # 获取原始文件名
                if not filename:
                    # 尝试从Content-Disposition获取文件名
                    cd = response.headers.get('Content-Disposition', '')
                    if 'filename=' in cd:
                        filename = cd.split('filename=')[-1].strip('"\'')
                    else:
                        # 从URL提取文件名
                        filename = url.split('/')[-1]
                        # 处理URL参数
                        if '?' in filename:
                            filename = filename.split('?')[0]
                    # 确保文件名不为空
                    if not filename:
                        filename = f"unknown_{int(time.time())}"
                
                # 下载并保存文件
                file_path = save_dir / filename
                async with aiofiles.open(file_path, 'wb') as f:
                    async for chunk in response.content.iter_chunked(1024):
                        await f.write(chunk)
                
                success_count += 1
                return True
                
        except Exception as e:
            if attempt < retry_times:
                await asyncio.sleep(0.5)  # 重试前短暂等待
                continue
            # 所有重试都失败
            fail_count += 1
            failed_urls.append(url)
            # 实时写入失败链接
            with open(ERROR_FILE, 'a', encoding='utf-8') as f:
                f.write(url + '\n')
            return False

async def process_batch(batch_num, batch_urls, concurrency, retry_times, timeout, save_dir):
    """
    处理单个批次的链接
    """
    timeout_obj = ClientTimeout(total=timeout)
    connector = aiohttp.TCPConnector(limit=concurrency)
    
    async with aiohttp.ClientSession(connector=connector, timeout=timeout_obj) as session:
        tasks = []
        for url in batch_urls:
            # 创建下载任务（传入保存目录）
            task = asyncio.create_task(download_file(session, url, retry_times, timeout_obj.total, save_dir))
            tasks.append(task)
        
        # 显示当前批次进度
        sys.stdout.write(f"\r处理批次{batch_num}/{total_batches}")
        sys.stdout.flush()
        
        # 等待所有任务完成
        await asyncio.gather(*tasks)

def read_urls_from_file(file_path):
    """
    从文件读取链接
    """
    urls = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            url = line.strip()
            if url:
                urls.append(url)
    return urls

async def main():
    global total_batches, total_count
    
    # 解析命令行参数，按指定格式配置帮助信息
    parser = argparse.ArgumentParser(
        description='批量文件下载工具',
        formatter_class=argparse.RawTextHelpFormatter,
        add_help=False
    )
    
    # 添加参数，新增-o参数
    parser.add_argument('-h', action='store_true', help='帮助')
    parser.add_argument('-u', '--url', help='单个下载链接')
    parser.add_argument('-f', '--file', help='包含下载链接的文件')
    parser.add_argument('-c', '--concurrency', type=int, default=20, help='下载并发数（默认20）')
    parser.add_argument('-t', '--timeout', type=int, default=30, help='单个链接下载超时时间（默认30秒）')
    parser.add_argument('-r', '--retry', type=int, default=3, help='下载失败后的重试次数（默认3次）')
    parser.add_argument('-b', '--batch', type=int, default=500, help='每批处理的链接数量（默认500）')
    parser.add_argument('-o', '--output', default="file", help='文件保存路径（默认file文件夹）')
    
    args = parser.parse_args()
    
    # 单独处理-h参数，按指定格式输出帮助信息（新增-o说明）
    if args.h:
        help_text = """options:
  -h            帮助
  -u            单个下载链接
  -f            包含下载链接的文件
  -c            下载并发数（默认20）
  -t            单个链接下载超时时间（默认30秒）
  -r            下载失败后的重试次数（默认3次）
  -b            每批处理的链接数量（默认500）
  -o            文件保存路径（默认file文件夹）"""
        print(help_text)
        sys.exit(0)
    
    # 验证参数
    if not args.url and not args.file:
        print("错误：-h查看帮助信息")
        sys.exit(1)
    
    # 处理保存路径（支持相对/绝对路径）
    save_dir = Path(args.output)
    # 确保保存目录存在（递归创建）
    save_dir.mkdir(parents=True, exist_ok=True)
    print(f"文件将保存到：{save_dir.absolute()}")
    
    # 获取所有链接
    if args.url:
        urls = [args.url]
    else:
        urls = read_urls_from_file(args.file)
    
    total_count = len(urls)
    print(f"成功获取{total_count}条链接")
    
    if total_count == 0:
        print("错误：未找到任何有效链接")
        sys.exit(1)
    
    # 计算批次数量
    total_batches = (total_count + args.batch - 1) // args.batch
    
    # 清空之前的失败文件
    if os.path.exists(ERROR_FILE):
        os.remove(ERROR_FILE)
    
    # 记录开始时间
    start_time = time.time()
    
    # 分批处理（传入保存目录）
    for batch_num in range(1, total_batches + 1):
        start_idx = (batch_num - 1) * args.batch
        end_idx = min(start_idx + args.batch, total_count)
        batch_urls = urls[start_idx:end_idx]
        
        await process_batch(batch_num, batch_urls, args.concurrency, args.retry, args.timeout, save_dir)
    
    # 计算总耗时
    total_seconds = time.time() - start_time
    minutes = int(total_seconds // 60)
    seconds = int(total_seconds % 60)
    time_str = f"{minutes}分钟{seconds}秒" if seconds else f"{minutes}分钟"
    
    # 输出最终统计
    print("\n任务完成！")
    print(f"总文件数：{total_count}")
    print(f"成功：{success_count}")
    print(f"失败：{fail_count}")
    print(f"总耗时：{time_str}")
    print(f"失败链接已保存到：{ERROR_FILE}")

if __name__ == "__main__":
    # 解决Windows下asyncio的兼容性问题
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    # 导入aiofiles（需要先安装：pip install aiofiles）
    try:
        import aiofiles
    except ImportError:
        print("错误：缺少aiofiles库")
        sys.exit(1)
    
    asyncio.run(main())