(() => {
  if (window.__inspectPluginLoaded) return;
  window.__inspectPluginLoaded = true;

  const btn = document.createElement('button');
  btn.textContent = 'Inspect';
  Object.assign(btn.style, {position:'fixed',right:'16px',bottom:'16px',zIndex:'999999',padding:'8px 12px',background:'#2563eb',color:'#fff',border:'none',borderRadius:'8px',cursor:'pointer',fontSize:'14px',lineHeight:'1.4'});
  document.body.appendChild(btn);

  const panel = document.createElement('div');
  Object.assign(panel.style, {position:'fixed',right:'16px',bottom:'64px',width:'360px',maxHeight:'60vh',overflow:'auto',background:'#fff',border:'1px solid #ddd',borderRadius:'8px',padding:'12px',zIndex:'999999',display:'none',fontSize:'13px',lineHeight:'1.5',color:'#111827',fontFamily:'-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif',boxShadow:'0 8px 24px rgba(0,0,0,.2)'});
  document.body.appendChild(panel);

  let inspectMode = false;
  let highlighted = null;
  const clearHighlight = () => {
    if (highlighted) {
      highlighted.style.boxShadow = highlighted.__oldBoxShadow || '';
      highlighted = null;
    }
  };
  const short = (el) => {
    if (!el) return '';
    const id = el.id ? `#${el.id}` : '';
    const cls = (el.className && typeof el.className === 'string') ? '.' + el.className.trim().split(/\s+/).slice(0,3).join('.') : '';
    return `${el.tagName.toLowerCase()}${id}${cls}`;
  };
  const ownText = (el) => Array.from(el.childNodes).filter(n => n.nodeType === Node.TEXT_NODE).map(n => n.textContent.trim()).filter(Boolean).join(' ');

  const renderFeedback = (picked, own) => {
    panel.innerHTML = '';
    const title = document.createElement('div');
    title.textContent = `已选择: ${short(picked)}`;
    panel.appendChild(title);
    const ta = document.createElement('textarea');
    ta.placeholder = '请输入修改意见';
    ta.style.width = '100%'; ta.style.height = '90px'; ta.style.marginTop = '8px'; ta.style.fontSize = '13px'; ta.style.lineHeight = '1.5'; ta.style.color = '#111827';
    panel.appendChild(ta);
    const submit = document.createElement('button');
    submit.textContent = '提交修改';
    submit.style.marginTop = '8px'; submit.style.fontSize = '13px'; submit.style.lineHeight = '1.4'; submit.style.color = '#111827';
    submit.onclick = async () => {
      const suggestion = ta.value.trim();
      if (!suggestion) return alert('请先输入修改意见');
      panel.innerHTML = '<div>正在运行中，请稍候...</div>';
      try {
        const res = await fetch('/api/preview-modify', {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({
            page_url: location.pathname,
            element_selector: short(picked),
            element_own_text: own,
            suggestion
          })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || '请求失败');
        panel.innerHTML = `<div>完成！新的预览 URL：<a href="${data.preview_url}" target="_blank">${data.preview_url}</a></div>`;
      } catch (e) {
        panel.innerHTML = `<div style="color:red;">失败: ${e.message}</div>`;
      }
    };
    panel.appendChild(submit);
  };

  const onClickCapture = (e) => {
    if (!inspectMode) return;
    e.preventDefault(); e.stopPropagation();
    const list = document.elementsFromPoint(e.clientX, e.clientY).filter(el => !panel.contains(el) && el !== btn && el !== panel);
    panel.style.display = 'block';
    panel.innerHTML = '<div style="margin-bottom:8px;">点击选择目标元素：</div>';
    list.forEach((el, idx) => {
      const item = document.createElement('div');
      item.textContent = `${idx+1}. ${short(el)}`;
      item.style.padding = '6px'; item.style.border='1px solid #eee'; item.style.marginBottom='4px'; item.style.cursor='pointer';
      item.style.fontSize = '13px'; item.style.lineHeight = '1.5'; item.style.color = '#111827';
      item.onmouseenter = () => {
        clearHighlight();
        highlighted = el;
        el.__oldBoxShadow = el.style.boxShadow;
        el.style.boxShadow = 'inset 0 0 0 2px #f97316';
      };
      item.onmouseleave = () => clearHighlight();
      item.onclick = (ev) => { ev.stopPropagation(); renderFeedback(el, ownText(el)); };
      panel.appendChild(item);
    });
  };

  btn.onclick = () => {
    inspectMode = !inspectMode;
    btn.textContent = inspectMode ? 'Inspect: ON' : 'Inspect';
    panel.style.display = inspectMode ? 'block' : 'none';
    if (inspectMode) panel.innerHTML = '<div>Inspect 模式已开启，请点击页面任意位置。</div>';
  };
  document.addEventListener('click', onClickCapture, true);
})();
