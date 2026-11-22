/** Runs inline in <head>. When one of the page's own script files fails to load (the page is
 *  older than the last deploy, or the connection dropped), the screen would stay drawn with no
 *  code behind its buttons: reload once to get the current page. At most once a minute, and never
 *  when the device refuses session storage (no way to prevent a loop). */
export const CHUNK_RECOVER = `addEventListener("error",function(e){var t=e.target;if(!t||t.tagName!=="SCRIPT"||String(t.src||"").indexOf("/_next/static/")<0)return;try{var k="reloaded-at",n=Date.now();if(n-(+sessionStorage.getItem(k)||0)<60000)return;sessionStorage.setItem(k,String(n))}catch(x){return}location.reload()},true)`;
