// probe_schedules.js — GROUND TRUTH from AniList's OWN per-title schedules.
// Run inside an anilist.co tab via browser_use execute_js. Generate it with:
//   sh scripts/verify_provenance.sh prepare /tmp/an/season.txt
// which substitutes IDS / EPOCH_FROM / EPOCH_TO below.
// Output: one line per id  ->  id \t n_eps \t weekday \t HH:MM \t first_date \t last_date
// (JST wall clock; see verify_provenance.sh check for the comparison.)
var IDS = __IDS__;
var G = __FROM__;
var L = __TO__;
var WD = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
function jst(e){ return new Date(e*1000 + 9*3600*1000); }
function key(e){ var d = jst(e); return WD[d.getUTCDay()] + " " + d.toISOString().slice(11,16); }
function ymd(d){ return d.getUTCFullYear()+"-"+String(d.getUTCMonth()+1).padStart(2,"0")+"-"+String(d.getUTCDate()).padStart(2,"0"); }
var by = {};
var CH = 25;
for (var c = 0; c < IDS.length; c += CH) {
  var chunk = IDS.slice(c, c + CH);
  for (var p = 1; p <= 20; p++) {
    var q = {query: "query($ids:[Int],$g:Int,$l:Int,$p:Int){Page(page:$p,perPage:50){airingSchedules(mediaId_in:$ids,airingAt_greater:$g,airingAt_lesser:$l){mediaId episode airingAt}}}",
             variables: {ids: chunk, g: G, l: L, p: p}};
    var r = await fetch("https://graphql.anilist.co", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(q)});
    var j = await r.json();
    if (!j.data) { return "ERR " + JSON.stringify(j.errors || j).slice(0,300); }
    var rows = j.data.Page.airingSchedules;
    for (var i = 0; i < rows.length; i++) {
      var x = rows[i];
      (by[x.mediaId] = by[x.mediaId] || []).push(x);
    }
    if (rows.length < 50) break;
  }
}
var out = [];
for (var k = 0; k < IDS.length; k++) {
  var id = IDS[k];
  var a = (by[id] || []).slice().sort(function(u,v){ return u.episode - v.episode; });
  if (!a.length) { out.push(id + "\t0\tNONE\tNONE\t\t\t"); continue; }
  // ep1 is often a 00:00 midnight placeholder, so weekday+clock come from the
  // modal of rows 2..N, never from row 1 alone.
  var pool = a.length > 1 ? a.slice(1) : a;
  var tally = {};
  for (var m = 0; m < pool.length; m++) { var kk = key(pool[m].airingAt); tally[kk] = (tally[kk]||0)+1; }
  var best = "", bn = 0;
  for (var t in tally) { if (tally[t] > bn) { bn = tally[t]; best = t; } }
  // Emit EVERY episode date so the checker can test the weekly lattice instead of
  // trusting one datapoint (placeholders, hiatuses, partially-purged rows).
  var dates = [];
  for (var z = 0; z < a.length; z++) { var s = ymd(jst(a[z].airingAt)); if (dates.indexOf(s) < 0) dates.push(s); }
  dates.sort();
  out.push(id + "\t" + a.length + "\t" + best.split(" ")[0] + "\t" + best.split(" ")[1]
              + "\t" + dates[0] + "\t" + dates[dates.length-1] + "\t" + dates.join(","));
}
return out.join("\n");
