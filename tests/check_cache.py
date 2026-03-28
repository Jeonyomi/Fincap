import sys, json, glob, os
sys.stdout.reconfigure(encoding="utf-8")

# 현대자동차 캐시 확인
for f in glob.glob("cache/co_*.json"):
    try:
        nm = os.path.basename(f)
        data = json.loads(open(f, encoding="utf-8").read())
        if isinstance(data, list) and any("현대자동차" in d.get("corp_name","") for d in data):
            print(f"파일: {nm}, {len(data)}개")
            for d in data:
                sq = d.get("stock_code","").strip()
                print(f"  {d['corp_name']} ({sq}) {'[상장]' if sq else '[비상장]'}")
    except: pass
