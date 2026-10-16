"""Build the report from real screenshots and measured evidence using bundled Python.

Run --check to validate without authoring. Run the builder only after the required
artifact operation markers. Export the matching PDF with packaged render_docx.py.
No evaluations are run, invented or inferred from scripted replay by this builder.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.shared import Inches, Pt, RGBColor
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "course-report"
REPO_URL = "https://github.com/aayushtiwari845/AutoHeal"
TEXT_WIDTH = 7.0
REFERENCES = [
    ("Yao et al 2023", "ReAct Synergizing Reasoning and Acting in Language Models", "https://arxiv.org/abs/2210.03629"),
    ("Shinn et al 2023", "Reflexion Language Agents with Verbal Reinforcement Learning", "https://arxiv.org/abs/2303.11366"),
    ("Python Software Foundation", "Subprocess management documentation", "https://docs.python.org/3/library/subprocess.html"),
    ("Ollama", "Generate a chat message and structured responses", "https://docs.ollama.com/api/chat"),
    ("Qwen Team", "Qwen2.5 Coder 7B Instruct official model card", "https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct"),
    ("Hui et al 2024", "Qwen2.5 Coder Technical Report", "https://arxiv.org/abs/2409.12186"),
    ("Microsoft", "Job Objects in the Windows process documentation", "https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects"),
    ("Python Software Foundation", "JSON encoder and decoder documentation", "https://docs.python.org/3/library/json.html"),
    ("Python Software Foundation", "CPython tracing and sys settrace documentation", "https://docs.python.org/3/library/sys.html#sys.settrace"),
    ("Project source and evidence", "AutoHeal repository", REPO_URL),
    ("Ollama", "Qwen2.5 Coder 7B quantized distribution", "https://ollama.com/library/qwen2.5-coder:7b"),
    ("Groq", "Compatible chat API documentation", "https://console.groq.com/docs/openai"),
]


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def resolve_file(value, relative_to=None):
    path = Path(value)
    if path.is_absolute(): return path
    rooted = ROOT / path
    if rooted.is_file() or relative_to is None: return rooted
    return Path(relative_to) / path


def replace_fields(value, context):
    if isinstance(value, str):
        def sub(match):
            key = match.group(1)
            if key not in context:
                raise ValueError(f"Unresolved report evidence field: {key}")
            return str(context[key])
        return re.sub(r"\{\{([a-z_]+)\}\}", sub, value)
    if isinstance(value, list): return [replace_fields(item, context) for item in value]
    if isinstance(value, dict): return {key: replace_fields(item, context) for key, item in value.items()}
    return value


def preflight(evidence_path):
    evidence = load_json(evidence_path)
    for name in ("version", "source_commit", "report_date", "python_version", "hardware", "test_log", "live_summary", "screenshot_index"):
        if not isinstance(evidence.get(name), str) or not evidence[name].strip():
            raise ValueError(f"Report requires observed evidence: {name}")
    if not re.fullmatch(r"[a-fA-F0-9]{7,64}", evidence["source_commit"]):
        raise ValueError("source_commit must identify the actual implementation revision")
    if not isinstance(evidence.get("test_count"), int) or evidence["test_count"] <= 0:
        raise ValueError("test_count must be an observed positive test count")
    if not isinstance(evidence.get("test_seconds"), (int, float)) or evidence["test_seconds"] <= 0:
        raise ValueError("test_seconds must be an observed duration")
    log = resolve_file(evidence["test_log"]).read_text(encoding="utf-8-sig")
    counts = re.findall(r"Ran\s+(\d+)\s+tests?", log)
    if not counts or int(counts[-1]) != evidence["test_count"] or not re.search(r"^OK\s*$", log, re.M):
        raise ValueError("Test evidence does not support the claimed passing test count")
    summary_path = resolve_file(evidence["live_summary"])
    summary = load_json(summary_path)
    runs = summary.get("runs", []) if isinstance(summary, dict) else summary
    if not isinstance(runs, list) or not runs: raise ValueError("Actual current evaluation records are required")
    for run in runs:
        if run.get("status") not in {"succeeded", "exhausted", "cancelled", "provider_error"}:
            raise ValueError("Evaluation records need actual terminal statuses")
        if "trace" not in run or not resolve_file(run["trace"], summary_path.parent).is_file():
            raise ValueError("Evaluation records must link existing traces")
        trace=load_json(resolve_file(run["trace"], summary_path.parent))
        if trace.get("control_mode") not in {"auto","manual"} or "stage_history" not in trace:
            raise ValueError("Current results require v2 traces with control mode and stage history")
        if trace.get("status")!=run["status"]:
            raise ValueError("Evaluation summary status differs from its saved trace")
        for key in ("mode","provider","control_mode","preset_id","model"):
            run.setdefault(key,trace.get(key))
        run.setdefault("attempts",trace["metrics"]["attempts"])
        run.setdefault("duration_ms",trace["metrics"]["duration_ms"])
    index = load_json(resolve_file(evidence["screenshot_index"]))
    if isinstance(index, dict) and "screenshots" in index: index = index["screenshots"]
    if isinstance(index, list): index = {entry["key"]: entry for entry in index}
    manuscript = load_json(SOURCE / "course_report.json")
    keys = {block["key"] for page in manuscript["pages"] for block in page["blocks"] if block["type"] == "screenshot"}
    for key in keys:
        if key not in index: raise ValueError(f"Missing actual screenshot stage: {key}")
        entry = index[key]
        if not entry.get("caption") or not entry.get("observation"):
            raise ValueError(f"Screenshot {key} needs a caption and observed evidence")
        with Image.open(resolve_file(entry["file"])) as picture: picture.verify()
    live = [run for run in runs if run.get("mode", "live") == "live"]
    context = dict(evidence)
    context.update(source_commit_short=evidence["source_commit"][:12], live_case_count=len(live),
        live_pass_count=sum(run["status"] == "succeeded" for run in live), test_seconds=f"{evidence['test_seconds']:.3f}",
        repo_url=REPO_URL, api_evaluation="A live external API run is included in the evidence." if evidence.get("api_live_tested") else "The optional API path is covered by automated transport tests; no measured live external API result is claimed here.")
    return evidence, replace_fields(manuscript, context), index, runs


def set_font(run, size=11, bold=False, name="Calibri", color="000000"):
    run.font.name=name
    run.font.size=Pt(size)
    run.font.bold=bold
    run.font.color.rgb=RGBColor.from_string(color)
    rpr=run._element.get_or_add_rPr()
    fonts=rpr.find(qn("w:rFonts"))
    if fonts is None: fonts=OxmlElement("w:rFonts"); rpr.append(fonts)
    for key in ("ascii","hAnsi","eastAsia","cs"): fonts.set(qn("w:"+key),name)


def paragraph(doc, content, size=11, bold=False, after=7, before=0, keep=False):
    p=doc.add_paragraph()
    fmt=p.paragraph_format
    fmt.space_before=Pt(before); fmt.space_after=Pt(after); fmt.line_spacing=1.08
    fmt.keep_together=keep; fmt.widow_control=True
    set_font(p.add_run(content),size,bold)
    return p


def heading(doc, value):
    p=doc.add_paragraph(style="Heading 2")
    p.paragraph_format.space_before=Pt(11); p.paragraph_format.space_after=Pt(5)
    p.paragraph_format.keep_with_next=True
    set_font(p.add_run(value),13,True)


def hyperlink(p, label, target, size=10):
    rid=p.part.relate_to(target,RT.HYPERLINK,is_external=True)
    link=OxmlElement("w:hyperlink"); link.set(qn("r:id"),rid)
    run=OxmlElement("w:r"); props=OxmlElement("w:rPr")
    fonts=OxmlElement("w:rFonts"); fonts.set(qn("w:ascii"),"Calibri"); fonts.set(qn("w:hAnsi"),"Calibri"); props.append(fonts)
    for tag,value in (("sz",str(round(size*2))),("color","000000")):
        item=OxmlElement("w:"+tag); item.set(qn("w:val"),value); props.append(item)
    run.append(props); text=OxmlElement("w:t"); text.text=label; run.append(text); link.append(run); p._p.append(link)


def data_table(doc, headers, rows, widths=None, size=10.3):
    widths=widths or [TEXT_WIDTH/len(headers)]*len(headers)
    if abs(sum(widths)-TEXT_WIDTH)>.02: raise ValueError("Table widths must total seven inches")
    table=doc.add_table(rows=1,cols=len(headers)); table.autofit=False; table.alignment=WD_TABLE_ALIGNMENT.CENTER
    for col,width in zip(table.columns,widths): col.width=Inches(width)
    borders=OxmlElement("w:tblBorders")
    for edge in ("top","left","bottom","right","insideH","insideV"):
        item=OxmlElement("w:"+edge)
        for key,value in (("val","single"),("sz","4"),("color","D9D9D9")): item.set(qn("w:"+key),value)
        borders.append(item)
    table._tbl.tblPr.append(borders)
    for ri,values in enumerate([headers]+list(rows)):
        row=table.rows[0] if ri==0 else table.add_row()
        row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
        if ri==0: row._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))
        for ci,(cell,value,width) in enumerate(zip(row.cells,values,widths)):
            cell.width=Inches(width); cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
            props=cell._tc.get_or_add_tcPr(); shade=OxmlElement("w:shd")
            shade.set(qn("w:fill"),"DFE7EC" if ri==0 else ("F6F8FA" if ri%2==0 else "FFFFFF")); props.append(shade)
            padding=OxmlElement("w:tcMar")
            for edge in ("top","bottom","left","right"):
                item=OxmlElement("w:"+edge); item.set(qn("w:w"),"90"); item.set(qn("w:type"),"dxa"); padding.append(item)
            props.append(padding); p=cell.paragraphs[0]
            p.paragraph_format.space_after=Pt(0); p.paragraph_format.line_spacing=1.03
            if width<=1.05: p.alignment=WD_ALIGN_PARAGRAPH.CENTER
            set_font(p.add_run(str(value)),size,ri==0)
    paragraph(doc,"",size=2,after=3)


def code_block(doc, source, size=9.6):
    p=doc.add_paragraph(); p.paragraph_format.space_after=Pt(8)
    p.paragraph_format.line_spacing=1.03; p.paragraph_format.keep_together=True
    for i,line in enumerate(source.splitlines()):
        if i: p.add_run().add_break()
        set_font(p.add_run(line),size,name="Consolas")


def figure(doc, path, caption, number, max_height=4):
    with Image.open(path) as image: width,height=image.size
    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before=Pt(4); p.paragraph_format.space_after=Pt(5); p.paragraph_format.keep_with_next=True
    inline=p.add_run().add_picture(str(path),width=Inches(min(TEXT_WIDTH,max_height*width/height)))
    inline._inline.docPr.set("descr",caption)
    paragraph(doc,f"Figure {number}  {caption}",size=9.8,after=8,keep=True)


def diagram_asset(kind,directory):
    """Explanatory diagrams derived from source; these are not UI screenshots."""
    image=Image.new("RGB",(1680,700),"white"); draw=ImageDraw.Draw(image)
    bold_fonts=(Path("C:/Windows/Fonts/calibrib.ttf"),Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))
    normal_fonts=(Path("C:/Windows/Fonts/calibri.ttf"),Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
    font=ImageFont.truetype(str(next(path for path in bold_fonts if path.exists())),36)
    small=ImageFont.truetype(str(next(path for path in normal_fonts if path.exists())),30)
    def box(rect,title,lines):
        draw.rounded_rectangle(rect,12,fill="#F3F6F8",outline="#8D9BA7",width=2)
        x0,y0,x1,y1=rect; draw.text(((x0+x1)/2,y0+38),title,anchor="mm",fill="black",font=font)
        for index,line in enumerate(lines): draw.text(((x0+x1)/2,y0+85+index*33),line,anchor="mm",fill="#24323E",font=small)
    def arrow(points):
        draw.line(points,fill="#415567",width=4); end,prev=points[-1],points[-2]
        dx,dy=end[0]-prev[0],end[1]-prev[1]
        if abs(dx)>abs(dy):
            direction=1 if dx>0 else -1; tip=[end,(end[0]-direction*15,end[1]-8),(end[0]-direction*15,end[1]+8)]
        else:
            direction=1 if dy>0 else -1; tip=[end,(end[0]-8,end[1]-direction*15),(end[0]+8,end[1]-direction*15)]
        draw.polygon(tip,fill="#415567")
    if kind=="architecture":
        box((40,70,420,260),"Browser dashboard",["Task and flow controls","Candidate and trace views","No generated code execution"])
        box((620,70,1060,260),"Local Python service",["HTTP API and RunManager","Bounded state machine","Trace and validation"])
        box((1260,70,1640,260),"Model provider",["Local Ollama by default","Optional configured API","Code and concise diagnosis"])
        box((620,440,1060,630),"Constrained child",["Fresh temporary workspace","Timeout and bounded output","stdout  stderr  returncode"])
        box((1260,440,1640,630),"Independent oracle",["Fixed preset references","Finite numeric comparisons","Custom structure only"])
        arrow([(420,165),(620,165)]); arrow([(1060,165),(1260,165)])
        arrow([(840,260),(840,440)]); arrow([(1060,535),(1260,535)])
        arrow([(1450,440),(1450,350),(1030,350),(1030,260)])
        draw.text((800,335),"Run candidate",anchor="rm",font=small,fill="#24323E")
        draw.text((330,535),"Orchestration stays local.\nAPI mode can send task data\nto an external provider.",anchor="mm",font=small,fill="#24323E",align="center")
    else:
        boxes=[(40,90,360,250),(450,90,770,250),(860,90,1180,250),(1270,90,1590,250)]
        names=["Generate","Execute","Evaluate","Reflect"]
        lines=[["Complete candidate","Source and diagnosis"],["Inspect and run child","Capture evidence"],["JSON and oracle","Stop on validated pass"],["Bound failure evidence","Prepare next repair"]]
        for rect,title,detail in zip(boxes,names,lines): box(rect,title,detail)
        for a,b in zip(boxes,boxes[1:]): arrow([(a[2],170),(b[0],170)])
        arrow([(1430,250),(1430,345),(200,345),(200,250)])
        draw.text((820,385),"A failed evaluation returns to generation while attempts remain",anchor="mm",font=small,fill="#24323E")
        box((230,465,1450,630),"Control and termination",["Automatic flow advances; manual flow waits at exposed phase boundaries.","Success, cancellation, provider failure or exhausted budget ends the run. N <= 5."])
    path=directory/f"{kind}.png"; image.save(path); return path


def new_document(evidence):
    doc=Document(); sec=doc.sections[0]
    sec.page_width,sec.page_height=Inches(8.5),Inches(11)
    sec.top_margin=sec.bottom_margin=Inches(.65); sec.left_margin=sec.right_margin=Inches(.75)
    sec.header_distance=sec.footer_distance=Inches(.28)
    for name in ("Normal","Title","Subtitle","Heading 1","Heading 2","Heading 3","Caption","Header","Footer"):
        style=doc.styles[name]; style.font.name="Calibri"; style.font.color.rgb=RGBColor(0,0,0); style.font.size=Pt(11)
        props=style._element.find(qn("w:pPr"))
        if props is not None:
            for item in list(props):
                if item.tag==qn("w:pBdr"): props.remove(item)
    doc.styles["Normal"].paragraph_format.line_spacing=1.08
    set_font(sec.header.paragraphs[0].add_run("AutoHeal  |  Generative AI Laboratory Project"),8.5)
    footer=sec.footer.paragraphs[0]; footer.alignment=WD_ALIGN_PARAGRAPH.RIGHT
    set_font(footer.add_run(f"Version {evidence['version']}  |  "),8.5)
    field=OxmlElement("w:fldSimple"); field.set(qn("w:instr"),"PAGE"); footer._p.append(field)
    doc.core_properties.title="AutoHeal Code Execution and Self Correction"
    doc.core_properties.subject="Generative AI laboratory project 216U42E734"
    doc.core_properties.author="Aayush Kumar Tiwari and Prateeksha Kini"
    return doc


def evaluation_rows(runs):
    rows=[]
    for run in runs:
        mode=run.get("mode","live"); seeded=bool(run.get("seeded",run.get("seed_failure",False)))
        label="Replay" if mode=="replay" else ("Live seeded" if seeded else "Live generated")
        rows.append([label,str(run.get("flow",run.get("control_mode","automatic"))),str(run.get("preset",run.get("preset_id","custom"))).title(),run.get("attempts",0),f"{run.get('duration_ms',0)/1000:.2f}",run["status"]])
    return rows


def build(evidence,manuscript,screenshots,runs):
    target=ROOT/"docs"/"report"; assets=ROOT/"tmp"/"report-assets"
    target.mkdir(parents=True,exist_ok=True); assets.mkdir(parents=True,exist_ok=True)
    doc=new_document(evidence); figure_number=0
    for page_index,page in enumerate(manuscript["pages"]):
        p=doc.add_paragraph(style="Title" if page_index==0 else "Heading 1")
        p.paragraph_format.page_break_before=page_index>0; p.paragraph_format.keep_with_next=True
        p.paragraph_format.space_after=Pt(11); p.paragraph_format.line_spacing=1
        set_font(p.add_run(page["title"]),26 if page_index==0 else 21)
        for block in page["blocks"]:
            kind=block["type"]
            if kind=="p": paragraph(doc,block["text"],size=block.get("size",11),bold=block.get("bold",False))
            elif kind=="h2": heading(doc,block["text"])
            elif kind=="code": code_block(doc,block["text"],size=block.get("size",9.6))
            elif kind=="table": data_table(doc,block["headers"],block["rows"],block.get("widths"),block.get("size",10.3))
            elif kind=="link": hyperlink(paragraph(doc,"",after=6),block["label"],block["url"],block.get("size",10))
            elif kind=="diagram":
                figure_number+=1; figure(doc,diagram_asset(block["kind"],assets),block["caption"],figure_number,block.get("max_height",3.7))
            elif kind=="screenshot":
                entry=screenshots[block["key"]]; figure_number+=1
                figure(doc,resolve_file(entry["file"]),entry["caption"],figure_number,block.get("max_height",4.2))
                paragraph(doc,entry["observation"],size=10.7)
                if entry.get("run_id"): paragraph(doc,"Evidence run "+str(entry["run_id"])+"  |  Mode "+str(entry.get("mode","recorded in trace")),size=9.3)
            elif kind=="results": data_table(doc,["Mode","Flow","Task","Attempts","Seconds","Outcome"],evaluation_rows(runs),[1.4,.7,.85,.85,1.0,2.2],10.3)
            elif kind=="evidence_index":
                for run in runs: paragraph(doc,f"{run.get('preset',run.get('preset_id','custom'))}  |  {run.get('flow','automatic')}  |  {run['status']}  |  {run['trace']}",size=9.3,after=4)
            elif kind=="references":
                for index,(author,title,url) in enumerate(REFERENCES,1):
                    p=paragraph(doc,f"[{index}] {author}. {title}.",size=9.4,after=1); p.paragraph_format.keep_with_next=True
                    hyperlink(paragraph(doc,"",size=9.2,after=3),url,url,9.2)
            else: raise ValueError(f"Unknown report block {kind}")
    path=target/"AutoHeal_Project_Report.docx"; doc.save(path); return path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence",type=Path,default=SOURCE/"evidence.json")
    parser.add_argument("--check",action="store_true",help="Validate evidence without authoring artifacts")
    args=parser.parse_args(); evidence,manuscript,screenshots,runs=preflight(args.evidence)
    print(json.dumps({"pages_planned":len(manuscript["pages"]),"screenshots":len(screenshots),"evaluations":len(runs),"source_commit":evidence["source_commit"]},indent=2))
    if not args.check: print(build(evidence,manuscript,screenshots,runs))


if __name__=="__main__": main()
