#!/bin/bash
# Scriber status one-shot — run on neo host:  bash /root/scriber-status.sh
# Gathers: CTs, GPUs, NFS, Supabase, API, workers, queue, DB stats, disk/RAM
H="=============================="

echo "$H SCRIBER STATUS — $(date) $H"

echo; echo "--- CONTAINERS ---"
pct list | tail -n +2 | grep -E '^20[1-5]'

echo; echo "--- HOST GPUs ---"
nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used,memory.total --format=csv,noheader

echo; echo "--- GPU CTs ---"
echo "204: $(pct exec 204 -- /usr/local/bin/nvidia-smi -L 2>/dev/null || echo FAIL)"
echo "205: $(pct exec 205 -- /usr/local/bin/nvidia-smi -L 2>/dev/null || echo FAIL)"

echo; echo "--- NFS mounts ---"
for i in 202 203 204 205; do
  s=$(pct exec $i -- sh -c 'findmnt /mnt/media >/dev/null && echo OK || echo NO-MOUNT' 2>/dev/null)
  echo "  $i: $s"
done

echo; echo "--- SERVICES ---"
echo "  api(202):    $(pct exec 202 -- systemctl is-active transcriber-api 2>/dev/null)"
echo "  redis(203):  $(pct exec 203 -- systemctl is-active redis-server 2>/dev/null)"
echo "  worker(203): $(pct exec 203 -- systemctl is-active rq-worker@203 2>/dev/null)"
echo "  worker(204): $(pct exec 204 -- systemctl is-active rq-worker@204 2>/dev/null)"
echo "  worker(205): $(pct exec 205 -- systemctl is-active rq-worker@205 2>/dev/null)"

echo; echo "--- REDIS QUEUE ---"
echo "  queued jobs:  $(pct exec 203 -- redis-cli llen transcribe 2>/dev/null)"
echo "  workers up:   $(pct exec 203 -- redis-cli smembers rq:workers 2>/dev/null | grep -c worker)"

echo; echo "--- SUPABASE (201) ---"
pct exec 201 -- docker ps --format '  {{.Names}}: {{.Status}}' | sort
echo "  201 RAM: $(pct exec 201 -- free -m 2>/dev/null | awk '/Mem:/{print $3"MB used / "$2"MB total"}')"

echo; echo "--- API ---"
echo "  health: $(pct exec 202 -- curl -s -m 5 http://localhost:8001/api/health 2>/dev/null || echo UNREACHABLE)"

echo; echo "--- DB TOTALS ---"
pct exec 201 -- docker exec supabase-db psql -U supabase_admin -d postgres -tAc "
select rpad('videos',12)||count(*)||' ('||coalesce(sum(size_bytes)/1048576,0)||' MB)' from videos
union all select rpad('transcripts',12)||count(*) from transcripts
union all select rpad('segments',12)||count(*) from segments
union all select rpad('jobs',12)||count(*) from jobs
union all select rpad('users',12)||(select count(*) from auth.users);" | sed 's/^/  /'

echo; echo "--- JOBS BY STATUS ---"
pct exec 201 -- docker exec supabase-db psql -U supabase_admin -d postgres -tAc "
select stage||': '||count(*) from jobs group by stage order by stage desc;" | sed 's/^/  /'
pct exec 201 -- docker exec supabase-db psql -U supabase_admin -d postgres -tAc "
select 'videos '||status||': '||count(*) from videos group by status order by status;" | sed 's/^/  /'

echo; echo "--- RECENT JOBS (last 5) ---"
pct exec 201 -- docker exec supabase-db psql -U supabase_admin -d postgres -tAc "
select to_char(j.updated_at,'MM-DD HH24:MI')||' '||rpad(left(v.filename,18),19)||rpad(j.stage,13)||j.progress||'%'||
  case when j.error is not null then ' ERR: '||left(j.error,40) else '' end
from jobs j join videos v on v.id=j.video_id order by j.updated_at desc limit 5;" | sed 's/^/  /'

echo; echo "--- NFS USAGE ---"
pct exec 202 -- bash -c 'du -sh /mnt/media/videos/ 2>/dev/null' | sed 's/^/  media: /'
df -h /mnt/transcriber-nfs 2>/dev/null | tail -1 | awk '{print "  TrueNAS share: "$3" used, "$4" free ("$5")"}'

echo; echo "--- LXC RESOURCES ---"
for i in 201 202 203 204 205; do
  mem=$(pct exec $i -- free -m 2>/dev/null | awk '/Mem:/{print $3"MB/"$2"MB"}')
  disk=$(pct exec $i -- df -BG / 2>/dev/null | awk 'NR==2{print $3"/"$2}')
  echo "  $i: RAM $mem | rootfs $disk"
done

echo; echo "$H END $(date +%H:%M:%S) $H"
