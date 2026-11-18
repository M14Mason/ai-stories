const s=JSON.parse(require('fs').readFileSync(process.argv[2]));
s.scenes.forEach((sc,i)=>{for(const k of ['build','anim']){if(sc[k]){try{new Function('R','tl','S','D',sc[k]);}catch(e){console.log('SYNTAX',i,k,e.message);}}}});
console.log('checked',s.scenes.length);
