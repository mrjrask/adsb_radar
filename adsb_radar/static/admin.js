// The admin page's sky dome and side view (admin.py streams this file from flash into the page).
(function(){var S=['N','NE','E','SE','S','SW','W','NW'],R=100,C=120,NS='http://www.w3.org/2000/svg',
svg=document.getElementById('dome'),box=document.getElementById('domebox');
if(!svg||!svg.setPointerCapture)return;
var mi=document.getElementById('MIN_ELEVATION'),rg=document.getElementById('minr'),
mv=document.getElementById('minv'),hs=[],hh=[],drag=null,poly,
sd=document.getElementById('side'),st=document.getElementById('sidet'),un=document.getElementById('unit'),
mr=document.getElementById('MAX_RANGE'),he=document.getElementById('HOME_ELEVATION_FT'),
ax=0,ab=[],sdrag=null,G=128,SR=105,axl;
try{ax=(+localStorage.adsbAxis||0)%4;if(localStorage.adsbUnit)un.value=localStorage.adsbUnit}catch(e){}
// The renderer reports the configured distance unit.
var su=document.getElementById('srvunit');
if(su&&su.value){un.value=su.value=='mi'?'5280':su.value=='km'?'3280.84':'6076.12';un.disabled=true}
function mk(p,n,a){var e=document.createElementNS(NS,n);for(var k in a)e.setAttribute(k,a[k]);
p.appendChild(e);return e}
function el(n,a){return mk(svg,n,a)}
function num(i){var v=parseFloat(i.value);if(isNaN(v)){var m=/-?\d+(\.\d+)?$/.exec(i.placeholder);
v=m?parseFloat(m[0]):NaN}return v}
function base(){var v=num(mi);return isNaN(v)?0:v}
function val(i){var v=num(hs[i]);return isNaN(v)?base():v}
function pt(i,e){var a=i*Math.PI/4,r=(90-e)/90*R;return[C+r*Math.sin(a),C-r*Math.cos(a)]}
function ft(v){return Math.round(v).toLocaleString()+' ft'}
el('circle',{cx:C,cy:C,r:R,fill:'#4a3324'});poly=el('polygon',{fill:'#2a7a3a','fill-opacity':.85});
[0,30,60].forEach(function(e){var r=(90-e)/90*R;el('circle',{cx:C,cy:C,r:r,fill:'none',stroke:'#888',
'stroke-opacity':.5});el('text',{x:C+3,y:C-r+9,fill:'#ccc','font-size':8}).textContent=e+'\u00b0'});
S.forEach(function(n,i){var a=pt(i,0),b=pt(i,90),t=pt(i,-14);hs[i]=document.querySelector('[name=H_'+n+']');
el('line',{x1:a[0],y1:a[1],x2:b[0],y2:b[1],stroke:'#888','stroke-opacity':.4});
el('text',{x:t[0],y:t[1]+3,fill:'#eee','font-size':10,'text-anchor':'middle'}).textContent=n});
axl=el('line',{stroke:'#fc6','stroke-dasharray':'4 3','stroke-opacity':.8});
S.forEach(function(n,i){var g=el('circle',{r:10,stroke:'#111','data-i':i,style:'cursor:grab'}),
t=el('text',{'font-size':9,'text-anchor':'middle',fill:'#111','pointer-events':'none'});hh[i]=[g,t];
hs[i].addEventListener('input',draw)});
[0,1,2,3].forEach(function(a){var b=document.createElement('button');b.type='button';
b.textContent=S[a+4]+' \u2013 '+S[a];b.style.margin='0';b.onclick=function(){ax=a;
try{localStorage.adsbAxis=a}catch(e){}draw()};document.getElementById('axes').appendChild(b);ab[a]=b});
// The side view: sector ax on the right, its opposite on the left, home in the middle.
function side(){while(sd.firstChild)sd.removeChild(sd.firstChild);
var u=parseFloat(un.value)||6076.12,D=num(mr),H=num(he),ext,r,step,k,y,ls=[ax+4,ax],w=[];
if(isNaN(D)||D<=0)D=10;if(isNaN(H))H=0;
ext=[1,2,3,5,10,15,20,30,50,100].filter(function(x){return x>=D})[0]||D;r=SR*D/ext;
step=[500,1000,2000,5000,10000,20000,50000].filter(function(x){return ext*u/x<=5})[0]||100000;
mk(sd,'rect',{x:0,y:G,width:240,height:154-G,fill:'#4a3324'});
for(k=Math.floor(H/step)+1;;k++){y=G-(k*step-H)*SR/(ext*u);if(y<18)break;
mk(sd,'line',{x1:0,x2:240,y1:y,y2:y,stroke:'#888','stroke-opacity':.35});
mk(sd,'text',{x:2,y:y-2,fill:'#aaa','font-size':7}).textContent=(k*step>=1000?k*step/1000+'k':k*step)}
ls.forEach(function(s,j){var e=val(s)*Math.PI/180,d=j?1:-1;w[j]=[C+d*r*Math.cos(e),G-r*Math.sin(e),e];
mk(sd,'path',{d:'M'+C+' '+G+'L'+(C+d*r)+' '+G+'A'+r+' '+r+' 0 0 '+(j?0:1)+' '+w[j][0]+' '+w[j][1]+'Z',
fill:'#4a3324','fill-opacity':.6})});
mk(sd,'path',{d:'M'+C+' '+G+'L'+w[0][0]+' '+w[0][1]+'A'+r+' '+r+' 0 0 1 '+w[1][0]+' '+w[1][1]+'Z',
fill:'#2a7a3a','fill-opacity':.85});
mk(sd,'path',{d:'M'+(C-r)+' '+G+'A'+r+' '+r+' 0 0 1 '+(C+r)+' '+G,fill:'none',stroke:'#ccc',
'stroke-dasharray':'3 3'});
[-1,-.5,.5,1].forEach(function(f){var x=C+f*SR;mk(sd,'line',{x1:x,x2:x,y1:G,y2:G+4,stroke:'#ccc'});
mk(sd,'text',{x:x,y:G+13,fill:'#ccc','font-size':7,'text-anchor':'middle'}).textContent=
Math.abs(f)*ext+(Math.abs(f)==1?' '+un.options[un.selectedIndex].text:'')});
mk(sd,'circle',{cx:C,cy:G,r:3,fill:'#eee'});
mk(sd,'text',{x:C,y:G+22,fill:'#eee','font-size':7,'text-anchor':'middle'}).textContent='home '+ft(H);
ls.forEach(function(s,j){mk(sd,'text',{x:j?236:4,y:12,fill:'#eee','font-size':10,
'text-anchor':j?'end':'start'}).textContent=S[s];
mk(sd,'circle',{cx:w[j][0],cy:w[j][1],r:9,stroke:'#111','data-s':s,style:'cursor:grab',
fill:hs[s].value===''?'#999':'#fc6'});mk(sd,'text',{x:w[j][0],y:w[j][1]+3,'font-size':8,
'text-anchor':'middle',fill:'#111','pointer-events':'none'}).textContent=Math.round(val(s))});
st.textContent='At '+D+' '+un.options[un.selectedIndex].text+' out, a plane must be above '
+ft(H+D*u*Math.sin(w[0][2]))+' to the '+S[ax+4]+' and '+ft(H+D*u*Math.sin(w[1][2]))+' to the '+S[ax]
+'. Straight up, it shows below '+ft(H+D*u)+'.';
ab.forEach(function(b,a){b.className=a==ax?'':'plain'})}
function draw(){var pts=[];S.forEach(function(n,i){var e=val(i),p=pt(i,e);pts.push(p.join(','));
hh[i][0].setAttribute('cx',p[0]);hh[i][0].setAttribute('cy',p[1]);
hh[i][0].setAttribute('fill',hs[i].value===''?'#999':'#fc6');
hh[i][1].setAttribute('x',p[0]);hh[i][1].setAttribute('y',p[1]+3);
hh[i][1].textContent=Math.round(e)});poly.setAttribute('points',pts.join(' '));
var a=pt(ax,0),b=pt(ax+4,0);axl.setAttribute('x1',a[0]);axl.setAttribute('y1',a[1]);
axl.setAttribute('x2',b[0]);axl.setAttribute('y2',b[1]);
rg.value=base();mv.textContent=base()+'\u00b0';side()}
function at(s,ev){var r=s.getBoundingClientRect(),k=240/r.width;
return[(ev.clientX-r.left)*k,(ev.clientY-r.top)*k]}
svg.addEventListener('pointerdown',function(ev){var i=ev.target.getAttribute('data-i');
if(i===null)return;drag=+i;ax=drag%4;svg.setPointerCapture(ev.pointerId);ev.preventDefault();draw()});
svg.addEventListener('pointermove',function(ev){if(drag===null)return;var p=at(svg,ev),
x=p[0]-C,y=p[1]-C,
e=Math.max(0,Math.min(89,Math.round(90-Math.sqrt(x*x+y*y)/R*90)));hs[drag].value=e;draw()});
svg.addEventListener('pointerup',function(){drag=null});
svg.addEventListener('pointercancel',function(){drag=null});
sd.addEventListener('pointerdown',function(ev){var s=ev.target.getAttribute('data-s');
if(s===null)return;sdrag=+s;sd.setPointerCapture(ev.pointerId);ev.preventDefault()});
sd.addEventListener('pointermove',function(ev){if(sdrag===null)return;var p=at(sd,ev),
x=(sdrag<4?1:-1)*(p[0]-C),e=Math.atan2(G-p[1],x)*180/Math.PI;
hs[sdrag].value=Math.max(0,Math.min(89,Math.round(e)));draw()});
sd.addEventListener('pointerup',function(){sdrag=null});
sd.addEventListener('pointercancel',function(){sdrag=null});
un.addEventListener('change',function(){try{localStorage.adsbUnit=un.value}catch(e){}draw()});
[mr,he].forEach(function(i){if(i)i.addEventListener('input',draw)});
rg.addEventListener('input',function(){mi.value=rg.value;draw()});mi.addEventListener('input',draw);
document.getElementById('clr').addEventListener('click',function(){hs.forEach(function(i){i.value=''});
draw()});
// A saved HORIZON replaces the inherited one (config.json's) whole,
// so once any direction is set, the blank ones keep the cutoff their hint shows.
mi.form.addEventListener('submit',function(){if(hs.some(function(i){return i.value!==''}))
hs.forEach(function(i){var m=/\d+(\.\d+)?$/.exec(i.placeholder);if(i.value===''&&m)i.value=m[0]})});
box.hidden=false;draw()})();
