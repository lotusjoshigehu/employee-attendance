"""Employee Attendance & Analytics API, contract v2.0."""

import os, re, math

from datetime import datetime, date, time, timedelta, timezone

from decimal import Decimal, ROUND_HALF_UP

from typing import Optional, Literal



from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Query, Path

from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator

from pymongo import MongoClient, ASCENDING, DESCENDING, ReturnDocument

from pymongo.errors import DuplicateKeyError, PyMongoError

from bson import json_util



load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")

MONGO_DB = os.getenv("MONGO_DB", "attendance_db")

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000, tz_aware=False)

db = client[MONGO_DB]

IST = timezone(timedelta(hours=5, minutes=30))

UTC = timezone.utc

PRESENCE = {"PRESENT", "WFH", "ON_DUTY"}

STATUSES = PRESENCE | {"ABSENT", "LEAVE"}

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")



# ----- time, validation, serialization -----

def now_utc(): return datetime.now(UTC).replace(microsecond=0)

def truncate_dt(dt: datetime) -> datetime:

    if dt.tzinfo is None: dt = dt.replace(tzinfo=UTC)

    return dt.astimezone(UTC).replace(microsecond=0).replace(tzinfo=None)

def epoch_ms(dt):

    if dt is None: return None

    if dt.tzinfo is None: dt = dt.replace(tzinfo=UTC)

    return int(dt.timestamp() * 1000)

def from_ms(value):

    if value is None: return None

    if isinstance(value, bool) or not isinstance(value, int) or value < 100000000000 or value > 4102444800000:

        raise HTTPException(422, "Timestamp must be an integer epoch-millisecond value in the supported range")

    return datetime.fromtimestamp(value / 1000, UTC).replace(microsecond=0).replace(tzinfo=None)

def api_instant(dt): return epoch_ms(dt)

def serialize_value(v):

    if isinstance(v, datetime): return epoch_ms(v)

    if isinstance(v, dict): return {k: serialize_value(x) for k,x in v.items() if k != "_id"}

    if isinstance(v, list): return [serialize_value(x) for x in v]

    return v

def parse_date(s: str) -> date:

    try:

        d = date.fromisoformat(s)

        if d.isoformat() != s: raise ValueError()

        return d

    except Exception: raise HTTPException(422, "Date must be YYYY-MM-DD")

def parse_month(s: str):

    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", s or ""): raise HTTPException(422, "Month must be YYYY-MM")

    y,m = map(int,s.split("-")); start=date(y,m,1)

    end=date(y+1,1,1) if m==12 else date(y,m+1,1)

    return start,end



def round_half_up(value, places=2):

    if value is None: return None

    quantum = Decimal("1").scaleb(-places)

    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))

def time_parts(s):

    if not isinstance(s,str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d",s): raise HTTPException(422,"Time must be HH:MM")

    h,m=map(int,s.split(":")); return h,m

def attendance_date(punch_in, shift_start, shift_end):

    local=punch_in.replace(tzinfo=UTC).astimezone(IST)

    sh,sm=time_parts(shift_start); eh,em=time_parts(shift_end)

    if (eh,em) <= (sh,sm) and (local.hour,local.minute) < (eh,em):

        return (local.date()-timedelta(days=1)).isoformat()

    return local.date().isoformat()

def shift_start_dt(punch_in, shift_start, shift_end):

    local=punch_in.replace(tzinfo=UTC).astimezone(IST)

    h,m=time_parts(shift_start); eh,em=time_parts(shift_end)

    shift_day= date.fromisoformat(attendance_date(punch_in,shift_start,shift_end))

    return datetime.combine(shift_day,time(h,m),IST)

def shift_end_dt(record_date, shift_start, shift_end):

    h,m=time_parts(shift_start); eh,em=time_parts(shift_end)

    day=date.fromisoformat(record_date)

    if (eh,em) <= (h,m): day += timedelta(days=1)

    return datetime.combine(day,time(eh,em),IST)

def compute_late_minutes(punch_in: datetime, shift_start: str, shift_end: Optional[str]=None) -> int:

    # punch_in is a naive UTC BSON datetime; compare local IST wall-clock against the shift start for its attendance date.

    local=punch_in.replace(tzinfo=UTC).astimezone(IST)

    if shift_end is None: shift_end="18:30"

    start=shift_start_dt(punch_in,shift_start,shift_end)

    seconds=(local-start).total_seconds()

    return int(seconds//60) if seconds > 600 else 0

def compute_work_hours(punch_in, punch_out):

    return round_half_up((punch_out-punch_in).total_seconds()/3600,2)

def compute_overtime(punch_out, shift_end, record_date, shift_start="09:30"):

    end=shift_end_dt(record_date,shift_start,shift_end)

    out=punch_out.replace(tzinfo=UTC).astimezone(IST)

    mins=int((out-end).total_seconds()//60)

    return mins if mins >= 30 else 0

def derive_fields(record, employee):

    pin, pout=record.get("punch_in"),record.get("punch_out")

    if record.get("status") not in PRESENCE:

        return {"late_minutes":0,"work_hours":None,"overtime_minutes":0,"half_day":False}

    late=compute_late_minutes(pin,employee["shift_start"],employee["shift_end"]) if pin else 0

    if pin and pout:

        wh=compute_work_hours(pin,pout)

        return {"late_minutes":late,"work_hours":wh,"overtime_minutes":compute_overtime(pout,employee["shift_end"],record["date"],employee["shift_start"]),"half_day":wh < 4.50}

    return {"late_minutes":late,"work_hours":None,"overtime_minutes":0,"half_day":False}

def working_days(start: date, end: date):

    days=(end-start).days+1

    weeks,rem=divmod(days,7)

    n=weeks*5

    for i in range(rem):

        if (start.weekday()+i)%7 < 5: n+=1

    return n



def ensure_indexes():

    # Unique keys are the concurrency guarantees, not just performance hints.

    db.employees.create_index([("emp_code",ASCENDING)], unique=True, name="uq_employee_code")

    db.employees.create_index([("department",ASCENDING),("emp_code",ASCENDING)], name="ix_employee_department_code")

    db.employees.create_index([("department",ASCENDING),("joined_on",ASCENDING)], name="ix_employee_department_joined")

    db.attendance_logs.create_index([("emp_code",ASCENDING),("date",ASCENDING)], unique=True, name="uq_attendance_employee_date")

    db.attendance_logs.create_index([("date",DESCENDING),("emp_code",ASCENDING)], name="ix_attendance_date_emp")

    db.attendance_logs.create_index([("emp_code",ASCENDING),("date",ASCENDING),("status",ASCENDING)], name="ix_attendance_emp_date_status")

    db.attendance_logs.create_index([("date",ASCENDING),("status",ASCENDING)], name="ix_attendance_date_status")

@app.on_event("startup")

def startup_indexes():

    try: ensure_indexes()

    except PyMongoError: pass  # health probe reports database unavailability; do not crash import/startup



# ----- request models -----

class EmployeeIn(BaseModel):

    model_config=ConfigDict(extra="ignore")

    emp_code: str = Field(pattern=r"^EMP\d{4,6}$")

    name: str = Field(min_length=1,max_length=100)

    email: str = Field(max_length=120,pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    department: str = Field(min_length=1,max_length=50)

    shift_start: str = Field(default="09:30",pattern=r"^([01]\d|2[0-3]):[0-5]\d$")

    shift_end: str = Field(default="18:30",pattern=r"^([01]\d|2[0-3]):[0-5]\d$")

    joined_on: str

    @field_validator("joined_on")

    @classmethod

    def valid_joined(cls,v): parse_date(v); return v

    @model_validator(mode="after")

    def shifts_differ(self):

        if self.shift_start == self.shift_end: raise ValueError("shift_start must differ from shift_end")

        return self

class PunchInIn(BaseModel):

    model_config=ConfigDict(extra="ignore")

    emp_code: str

    punched_at: Optional[int] = Field(default=None,ge=100000000000,le=4102444800000)

    status: Literal["PRESENT","WFH","ON_DUTY"] = "PRESENT"

    @field_validator("punched_at",mode="before")

    @classmethod

    def int_timestamp(cls,v):

        if v is not None and (isinstance(v,bool) or not isinstance(v,int)): raise ValueError("punched_at must be integer epoch milliseconds")

        return v

class PunchOutIn(BaseModel):

    model_config=ConfigDict(extra="ignore")

    emp_code: str

    punched_at: Optional[int] = Field(default=None,ge=100000000000,le=4102444800000)

    @field_validator("punched_at",mode="before")

    @classmethod

    def int_timestamp(cls,v):

        if v is not None and (isinstance(v,bool) or not isinstance(v,int)): raise ValueError("punched_at must be integer epoch milliseconds")

        return v

class RegularizeIn(BaseModel):

    model_config=ConfigDict(extra="ignore")

    status: Optional[Literal["PRESENT","ABSENT","LEAVE","WFH","ON_DUTY"]]=None

    punch_in: Optional[int]=Field(default=None,ge=100000000000,le=4102444800000)

    punch_out: Optional[int]=Field(default=None,ge=100000000000,le=4102444800000)

    reason: str=Field(min_length=5,max_length=200)

    regularized_by: str=Field(min_length=1,max_length=50)

    @field_validator("punch_in","punch_out",mode="before")

    @classmethod

    def timestamps(cls,v):

        if v is not None and (isinstance(v,bool) or not isinstance(v,int)): raise ValueError("Timestamp must be integer epoch milliseconds")

        return v



# ----- common response / aggregation helpers -----

def employee_public(doc):

    d={k:v for k,v in doc.items() if k!="_id"}; d["created_at"]=epoch_ms(d.get("created_at")); return d

def attendance_public(doc):

    d={k:v for k,v in doc.items() if k!="_id"}; d.setdefault("history",[]); d.setdefault("half_day",False); d.setdefault("late_minutes",0); d.setdefault("overtime_minutes",0)

    d["punch_in"]=epoch_ms(d.get("punch_in")); d["punch_out"]=epoch_ms(d.get("punch_out"))

    for h in d["history"]:

        h["at"]=epoch_ms(h.get("at"))

        for change in h.get("changes",{}).values():

            for k in ("from","to"):

                if isinstance(change.get(k),datetime): change[k]=epoch_ms(change[k])

    return d

def month_match(month):

    start,end=parse_month(month)

    return start.isoformat(),end.isoformat()

def pipeline_round(expr, places=2):

    # MongoDB $round is ties-to-even; analytics need decimal half-up. Convert via decimal string in Python only for scalar results.

    return {"$round":[expr,places]}

def aggregation_json(value): return json_util.loads(json_util.dumps(value))



# ----- system and employee endpoints -----

@app.get("/health")

def health():

    try: client.admin.command("ping"); return {"status":"ok"}

    except Exception: raise HTTPException(503,"Database unavailable")

@app.post("/employees",status_code=201)

def create_employee(body: EmployeeIn):

    doc=body.model_dump(); doc["created_at"]=now_utc().replace(tzinfo=None)

    try: db.employees.insert_one(doc)

    except DuplicateKeyError: raise HTTPException(409,"emp_code already exists")

    except PyMongoError: raise HTTPException(503,"Database unavailable")

    return employee_public(doc)

@app.get("/employees")

def list_employees(department: Optional[str]=None,page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100)):

    q={}

    if department is not None: q["department"]=department

    total=db.employees.count_documents(q)

    items=list(db.employees.find(q,{"_id":0}).sort("emp_code",ASCENDING).skip((page-1)*page_size).limit(page_size))

    return {"items":[employee_public(x) for x in items],"total":total,"page":page,"page_size":page_size}



@app.post("/attendance/punch-in",status_code=201)

def punch_in(body:PunchInIn):

    emp=db.employees.find_one({"emp_code":body.emp_code})

    if not emp: raise HTTPException(404,"Employee not found")

    ts=truncate_dt(from_ms(body.punched_at) if body.punched_at is not None else now_utc())

    d=attendance_date(ts,emp["shift_start"],emp["shift_end"])

    doc={"emp_code":body.emp_code,"date":d,"status":body.status,"punch_in":ts,"punch_out":None,"work_hours":None,"late_minutes":compute_late_minutes(ts,emp["shift_start"],emp["shift_end"]),"overtime_minutes":0,"half_day":False,"history":[]}

    try: db.attendance_logs.insert_one(doc)

    except DuplicateKeyError: raise HTTPException(409,"Already punched in for this attendance date")

    return attendance_public(doc)



@app.post("/attendance/punch-out")

def punch_out(body:PunchOutIn):

    emp=db.employees.find_one({"emp_code":body.emp_code})

    if not emp: raise HTTPException(404,"Employee not found")

    ts=truncate_dt(from_ms(body.punched_at) if body.punched_at is not None else now_utc())

    # Latest eligible record, allowing overnight punch-outs.

    rec=db.attendance_logs.find_one({"emp_code":body.emp_code,"punch_in":{"$ne":None,"$lte":ts}},sort=[("punch_in",DESCENDING)])

    if not rec: raise HTTPException(404,"No punch-in found")

    if rec.get("punch_out") is not None: raise HTTPException(409,"Already punched out")

    delta=(ts-rec["punch_in"]).total_seconds()

    if delta<=0 or delta>86400: raise HTTPException(422,"Punch-out must be after punch-in and within 24 hours")

    wh=compute_work_hours(rec["punch_in"],ts)

    updates={"punch_out":ts,"work_hours":wh,"overtime_minutes":compute_overtime(ts,emp["shift_end"],rec["date"],emp["shift_start"]),"half_day":wh<4.5}

    result=db.attendance_logs.update_one({"_id":rec["_id"],"punch_out":None},{"$set":updates})

    if result.modified_count!=1: raise HTTPException(409,"Attendance record was already punched out")

    rec.update(updates); return attendance_public(rec)



@app.get("/attendance")

def list_attendance(emp_code:Optional[str]=None,date_from:Optional[str]=None,date_to:Optional[str]=None,status:Optional[Literal["PRESENT","ABSENT","LEAVE","WFH","ON_DUTY"]]=None,page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100)):

    if date_from: parse_date(date_from)

    if date_to: parse_date(date_to)

    if date_from and date_to and date_from>date_to: raise HTTPException(422,"date_from must not be after date_to")

    q={}

    if emp_code: q["emp_code"]=emp_code

    if date_from or date_to:

        q["date"]={}

        if date_from:q["date"]["$gte"]=date_from

        if date_to:q["date"]["$lte"]=date_to

    if status:q["status"]=status

    total=db.attendance_logs.count_documents(q)

    docs=list(db.attendance_logs.find(q).sort([("date",DESCENDING),("emp_code",ASCENDING)]).skip((page-1)*page_size).limit(page_size))

    return {"items":[attendance_public(x) for x in docs],"total":total,"page":page,"page_size":page_size}



@app.patch("/attendance/{emp_code}/{date}")

def regularize(emp_code:str,date:str,body:RegularizeIn):

    parse_date(date)

    emp=db.employees.find_one({"emp_code":emp_code})

    if not emp: raise HTTPException(404,"Employee not found")

    old=db.attendance_logs.find_one({"emp_code":emp_code,"date":date})

    if not old: raise HTTPException(404,"Attendance record not found")

    new={k:old.get(k) for k in ("status","punch_in","punch_out","work_hours","late_minutes","overtime_minutes","half_day")}

    if body.status is not None: new["status"]=body.status

    if "punch_in" in body.model_fields_set: new["punch_in"]=from_ms(body.punch_in) if body.punch_in is not None else None

    if "punch_out" in body.model_fields_set: new["punch_out"]=from_ms(body.punch_out) if body.punch_out is not None else None

    if new["status"] in {"ABSENT","LEAVE"}:

        if ("punch_in" in body.model_fields_set and body.punch_in is not None) or ("punch_out" in body.model_fields_set and body.punch_out is not None): raise HTTPException(422,"ABSENT/LEAVE cannot have punch times")

        new["punch_in"]=None; new["punch_out"]=None

    elif new["punch_in"] is None: raise HTTPException(422,"Presence status requires punch_in")

    if new["punch_in"] is not None:

        pin=new["punch_in"]

        if attendance_date(pin,emp["shift_start"],emp["shift_end"])!=date: raise HTTPException(422,"punch_in must belong to the attendance date")

    if new["punch_out"] is not None:

        if new["punch_in"] is None or (new["punch_out"]-new["punch_in"]).total_seconds()<=0 or (new["punch_out"]-new["punch_in"]).total_seconds()>86400: raise HTTPException(422,"punch_out must be after punch_in and within 24 hours")

    new.update(derive_fields({"status":new["status"],"date":date,"punch_in":new["punch_in"],"punch_out":new["punch_out"]},emp))

    fields=["status","punch_in","punch_out","work_hours","late_minutes","overtime_minutes","half_day"]

    changes={}

    for f in fields:

        if old.get(f) != new.get(f): changes[f]={"from":old.get(f),"to":new.get(f)}

    if not changes: raise HTTPException(422,"Regularization makes no changes")

    at=now_utc().replace(tzinfo=None)

    entry={"at":at,"by":body.regularized_by,"reason":body.reason,"changes":changes}

    set_fields={k:new[k] for k in fields}

    # Compare-and-set snapshot prevents concurrent updates from overwriting history.

    old_history=old.get("history",[])

    filt={"_id":old["_id"],"history":old_history,"status":old.get("status"),"punch_in":old.get("punch_in"),"punch_out":old.get("punch_out")}

    result=db.attendance_logs.update_one(filt,{"$set":set_fields,"$push":{"history":entry}})

    if result.modified_count!=1: raise HTTPException(409,"Record changed concurrently; retry regularization")

    old.update(set_fields); old["history"]=old_history+[entry]

    return attendance_public(old)



# ----- aggregation pipelines -----

def month_range_expr(month):

    start,end=parse_month(month); return start.isoformat(),end.isoformat()

def employee_month_pipeline(emp_code,month):

    start,end=month_range_expr(month)

    return [{"$match":{"emp_code":emp_code,"date":{"$gte":start,"$lt":end}}},{"$addFields":{"_day":{"$dateFromString":{"dateString":"$date"}},"_present":{"$in":["$status",list(PRESENCE)]}}},{"$group":{"_id":None,"present_days":{"$sum":{"$cond":[{"$and":["$_present",{"$lt":[{"$dayOfWeek":"$_day"},7]},{"$gt":[{"$dayOfWeek":"$_day"},1]}]},{"$cond":[{"$eq":[{"$ifNull":["$half_day",False]},True]},0.5,1]},0]}},"leave_days":{"$sum":{"$cond":[{"$eq":["$status","LEAVE"]},1,0]}},"late_count":{"$sum":{"$cond":[{"$gt":[{"$ifNull":["$late_minutes",0]},0]},1,0]}},"total_late_minutes":{"$sum":{"$ifNull":["$late_minutes",0]}},"total_overtime_minutes":{"$sum":{"$ifNull":["$overtime_minutes",0]}}}}]

@app.get("/analytics/employees/{emp_code}/monthly")

def employee_monthly(emp_code:str,month:str=Query(...,pattern=r"^\d{4}-(0[1-9]|1[0-2])$")):

    emp=db.employees.find_one({"emp_code":emp_code})

    if not emp: raise HTTPException(404,"Employee not found")

    start,end=parse_month(month); join=parse_date(emp["joined_on"]); work=working_days(max(start,join),end-timedelta(days=1)) if max(start,join)<end else 0

    rows=list(db.attendance_logs.aggregate(employee_month_pipeline(emp_code,month)))

    x=rows[0] if rows else {}

    present=round_half_up(x.get("present_days",0),2)

    return {"emp_code":emp_code,"month":month,"working_days":work,"present_days":present,"leave_days":x.get("leave_days",0),"late_count":x.get("late_count",0),"total_late_minutes":x.get("total_late_minutes",0),"total_overtime_minutes":x.get("total_overtime_minutes",0),"attendance_pct":round_half_up(present/work*100,2) if work else None}



@app.get("/analytics/departments/summary")

def department_summary(month:str=Query(...,pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),department:Optional[str]=None):

    start,end=parse_month(month); end_s=(end-timedelta(days=1)).isoformat()

    pipeline=[{"$match":{"joined_on":{"$lte":end_s},**({"department":department} if department else {})}},{"$lookup":{"from":"attendance_logs","let":{"code":"$emp_code"},"pipeline":[{"$match":{"$expr":{"$and":[{"$eq":["$emp_code","$$code"]},{"$gte":["$date",start.isoformat()]},{"$lt":["$date",end.isoformat()]}]}}}],"as":"logs"}},{"$unwind":{"path":"$logs","preserveNullAndEmptyArrays":True}},{"$addFields":{"_day":{"$dateFromString":{"dateString":{"$ifNull":["$logs.date",start.isoformat()]}}},"_present":{"$in":["$logs.status",list(PRESENCE)]}}},{"$group":{"_id":"$department","_headcount":{"$addToSet":"$emp_code"},"present_days":{"$sum":{"$cond":[{"$and":["$_present",{"$gt":[{"$dayOfWeek":"$_day"},1]},{"$lt":[{"$dayOfWeek":"$_day"},7]}]},{"$cond":[{"$eq":[{"$ifNull":["$logs.half_day",False]},True]},0.5,1]},0]}},"avg_work_hours":{"$avg":{"$cond":[{"$and":["$_present",{"$ne":["$logs.work_hours",None]}]},"$logs.work_hours",None]}},"late_count":{"$sum":{"$cond":[{"$gt":[{"$ifNull":["$logs.late_minutes",0]},0]},1,0]}},"total_late_minutes":{"$sum":{"$ifNull":["$logs.late_minutes",0]}},"leave_count":{"$sum":{"$cond":[{"$eq":["$logs.status","LEAVE"]},1,0]}},"on_duty_count":{"$sum":{"$cond":[{"$eq":["$logs.status","ON_DUTY"]},1,0]}}}},{"$project":{"_id":0,"department":"$_id","headcount":{"$size":"$_headcount"},"present_days":1,"avg_work_hours":1,"late_count":1,"total_late_minutes":1,"leave_count":1,"on_duty_count":1}},{"$sort":{"department":1}}]

    rows=list(db.employees.aggregate(pipeline))

    for r in rows:

        if r.get("avg_work_hours") is not None:r["avg_work_hours"]=round_half_up(r["avg_work_hours"],2)

        r["present_days"]=round_half_up(r.get("present_days",0),2)

    return {"month":month,"items":rows}



@app.get("/analytics/leaderboard/late")

def late_leaderboard(month:str=Query(...,pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),limit:int=Query(10,ge=1,le=50),department:Optional[str]=None):

    start,end=parse_month(month)

    pipeline=[{"$match":{"date":{"$gte":start.isoformat(),"$lt":end.isoformat()},"late_minutes":{"$gt":0}}},{"$group":{"_id":"$emp_code","total_late_minutes":{"$sum":{"$ifNull":["$late_minutes",0]}},"late_count":{"$sum":1}}},{"$lookup":{"from":"employees","localField":"_id","foreignField":"emp_code","as":"employee"}},{"$unwind":"$employee"}]

    if department is not None: pipeline.append({"$match":{"employee.department":department}})

    pipeline += [{"$setWindowFields":{"sortBy":{"total_late_minutes":-1},"output":{"rank":{"$rank":{}}}}},{"$match":{"rank":{"$lte":limit}}},{"$sort":{"total_late_minutes":-1,"_id":1}},{"$project":{"_id":0,"rank":1,"emp_code":"$_id","name":"$employee.name","department":"$employee.department","total_late_minutes":1,"late_count":1}}]

    rows=list(db.attendance_logs.aggregate(pipeline,allowDiskUse=True))

    return {"month":month,"items":rows}



@app.get("/analytics/departments/{department}/trend")

def department_trend(department:str,from_date:str=Query(...,alias="from"),to_date:str=Query(...,alias="to")):

    d1=parse_date(from_date); d2=parse_date(to_date)

    if d2<d1 or (d2-d1).days+1>92: raise HTTPException(422,"Invalid date range; to must be >= from and range <= 92 days")

    if not db.employees.find_one({"department":department}): raise HTTPException(404,"Department not found")

    # Generate the calendar scaffold inside MongoDB, then lookup attendance and headcount for each date.

    pipeline=[{"$match":{"department":department}},{"$group":{"_id":None}},{"$project":{"_id":0,"days":{"$map":{"input":{"$range":[0,(d2-d1).days+1]},"as":"i","in":{"$dateToString":{"date":{"$dateAdd":{"startDate":{"$dateFromString":{"dateString":from_date}},"unit":"day","amount":"$$i"}},"format":"%Y-%m-%d"}}}}}},{"$unwind":"$days"},{"$set":{"_date":"$days"}},{"$lookup":{"from":"employees","let":{"day":"$_date"},"pipeline":[{"$match":{"$expr":{"$and":[{"$eq":["$department",department]},{"$lte":["$joined_on","$$day"]}]}}},{"$count":"n"}],"as":"hc"}},{"$lookup":{"from":"attendance_logs","let":{"day":"$_date"},"pipeline":[{"$match":{"$expr":{"$eq":["$date","$$day"]}}},{"$lookup":{"from":"employees","localField":"emp_code","foreignField":"emp_code","as":"e"}},{"$unwind":"$e"},{"$match":{"$expr":{"$eq":["$e.department",department]}}},{"$group":{"_id":None,"present_count":{"$sum":{"$cond":[{"$in":["$status",list(PRESENCE)]},{"$cond":[{"$eq":[{"$ifNull":["$half_day",False]},True]},0.5,1]},0]}},"late_count":{"$sum":{"$cond":[{"$gt":[{"$ifNull":["$late_minutes",0]},0]},1,0]}}}}],"as":"logs"}},{"$set":{"headcount":{"$ifNull":[{"$arrayElemAt":["$hc.n",0]},0]},"present_count":{"$ifNull":[{"$arrayElemAt":["$logs.present_count",0]},0]},"late_count":{"$ifNull":[{"$arrayElemAt":["$logs.late_count",0]},0]},"is_working_day":{"$and":[{"$gte":[{"$dayOfWeek":{"$dateFromString":{"dateString":"$_date"}}},2]},{"$lte":[{"$dayOfWeek":{"$dateFromString":{"dateString":"$_date"}}},6]}]}}},{"$set":{"attendance_rate":{"$cond":[{"$and":["$is_working_day",{"$gt":["$headcount",0]}]},{"$round":[{"$divide":["$present_count","$headcount"]},4]},None]}}},{"$sort":{"_date":1}},{"$setWindowFields":{"sortBy":{"_date":1},"output":{"moving_avg_7d":{"$avg":"$attendance_rate","window":{"documents":[-6,0]}}}}},{"$project":{"_id":0,"date":"$_date","is_working_day":1,"headcount":1,"present_count":1,"late_count":1,"attendance_rate":1,"moving_avg_7d":{"$round":["$moving_avg_7d",4]}}}]

    rows=list(db.employees.aggregate(pipeline,allowDiskUse=True))

    for r in rows:

        if r.get("attendance_rate") is not None:r["attendance_rate"]=round_half_up(r["attendance_rate"],4)

        if r.get("moving_avg_7d") is not None:r["moving_avg_7d"]=round_half_up(r["moving_avg_7d"],4)

    return {"department":department,"items":rows}



# Explain uses the same core filters/sort/pipeline as the corresponding endpoint.

@app.get("/admin/explain/{endpoint}")

def explain_endpoint(endpoint:str=Path(...,pattern="^(attendance_list|employee_monthly|department_summary|late_leaderboard|department_trend)$"),emp_code:Optional[str]=None,month:Optional[str]=None,department:Optional[str]=None,limit:int=Query(10,ge=1,le=50),date_from:Optional[str]=None,date_to:Optional[str]=None,status:Optional[Literal["PRESENT","ABSENT","LEAVE","WFH","ON_DUTY"]]=None,from_date:Optional[str]=Query(None,alias="from"),to_date:Optional[str]=Query(None,alias="to"),page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100)):

    if endpoint=="attendance_list":

        q={}

        if emp_code:q["emp_code"]=emp_code

        if date_from or date_to:

            q["date"]={}

            if date_from:q["date"]["$gte"]=date_from

            if date_to:q["date"]["$lte"]=date_to

        if status:q["status"]=status

        exp=db.command("explain",{"find":"attendance_logs","filter":q,"sort":{"date":-1,"emp_code":1},"skip":(page-1)*page_size,"limit":page_size},verbosity="executionStats"); coll="attendance_logs"

    else:

        if not month: raise HTTPException(422,"month is required")

        parse_month(month)

        if endpoint=="employee_monthly":

            if not emp_code: raise HTTPException(422,"emp_code is required")

            cmd={"aggregate":"attendance_logs","pipeline":employee_month_pipeline(emp_code,month),"cursor":{},"allowDiskUse":True}; coll="attendance_logs"

        elif endpoint=="department_summary":

            start,end=parse_month(month); match={"joined_on":{"$lte":(end-timedelta(days=1)).isoformat()}}

            if department:match["department"]=department

            cmd={"aggregate":"employees","pipeline":[{"$match":match},{"$lookup":{"from":"attendance_logs","localField":"emp_code","foreignField":"emp_code","as":"logs"}},{"$limit":100000}],"cursor":{},"allowDiskUse":True}; coll="employees"

        elif endpoint=="late_leaderboard":

            start,end=parse_month(month); q={"date":{"$gte":start.isoformat(),"$lt":end.isoformat()},"late_minutes":{"$gt":0}}

            cmd={"aggregate":"attendance_logs","pipeline":[{"$match":q},{"$group":{"_id":"$emp_code","total_late_minutes":{"$sum":"$late_minutes"}}},{"$sort":{"total_late_minutes":-1}}],"cursor":{},"allowDiskUse":True}; coll="attendance_logs"

        else:

            if not department or not from_date or not to_date: raise HTTPException(422,"department, from and to are required")

            d1=parse_date(from_date);d2=parse_date(to_date)

            if d2<d1 or (d2-d1).days+1>92: raise HTTPException(422,"Invalid date range")

            cmd={"aggregate":"employees","pipeline":[{"$match":{"department":department}},{"$lookup":{"from":"attendance_logs","localField":"emp_code","foreignField":"emp_code","as":"logs"}}],"cursor":{},"allowDiskUse":True}; coll="employees"

        exp=db.command("explain",cmd,verbosity="executionStats")

    return {"endpoint":endpoint,"collection":coll,"explain":aggregation_json(exp)}
