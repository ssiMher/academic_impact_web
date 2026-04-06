import sys
import requests
import time
import urllib.parse

def get_first_citation(query):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    paper_id = ""

    # 1. 智能判断输入类型：DOI、arXiv 还是 纯标题
    if "/" in query or query.startswith("10."):
        paper_id = f"DOI:{query}"
    elif query[0].isdigit() and "." in query: # 类似 1706.03762
        paper_id = f"ARXIV:{query}"
    else:
        # 如果是纯文本标题，先调用 search 接口获取 ID
        search_url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={urllib.parse.quote(query)}&limit=1"
        try:
            res = requests.get(search_url, headers=headers, timeout=15)
            if res.status_code == 200 and res.json().get('data'):
                paper_id = res.json()['data'][0]['paperId']
            else:
                return f"未在学术库中找到名为《{query}》的论文，请检查名称拼写。"
        except Exception as e:
            return f"搜索论文标题时网络出错: {e}"

    # 2. 根据获取到的 ID 查询引用
    citation_url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}/citations?fields=title,year,authors,venue"
    
    try:
        # 重试机制对抗限流
        for attempt in range(3):
            response = requests.get(citation_url, headers=headers, timeout=15)
            if response.status_code == 200:
                break
            elif response.status_code == 429:
                time.sleep(3)
            else:
                return f"获取引用失败。API 状态码: {response.status_code}。"

        if response.status_code != 200:
            return "尝试多次仍被服务器限流，请稍后再试。"

        data = response.json().get('data', [])
        if not data:
            return f"目前暂无其他文献引用该论文。"

        # 过滤并排序找首个引用
        valid_citations = [item['citingPaper'] for item in data if item.get('citingPaper') and item['citingPaper'].get('year')]
        if not valid_citations:
            return "找到引用记录，但缺少年份信息，无法判断首个引用。"

        sorted_citations = sorted(valid_citations, key=lambda x: x.get('year', 9999))
        first = sorted_citations[0]

        authors = ", ".join([a['name'] for a in first.get('authors', [])[:3]])
        if len(first.get('authors', [])) > 3:
            authors += " 等"

        return (f"【检索成功】\n"
                f"首次引用该工作的论文是：\n"
                f"标题: {first.get('title')}\n"
                f"年份: {first.get('year')}\n"
                f"作者: {authors}\n"
                f"期刊/会议: {first.get('venue', 'Unknown')}")

    except Exception as e:
        return f"脚本运行出错: {str(e)}"

if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(get_first_citation(sys.argv[1]))
    else:
        print("请提供论文标题、DOI 或 arXiv 编号。")
