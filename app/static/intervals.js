(()=>{
  const output=document.querySelector('#output');
  const dateInput=document.querySelector('#biz-date');
  const call=async(path,payload)=>{
    output.textContent='RUNNING';
    try{
      const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      const record=await response.json();
      if(!response.ok)throw Error(record.message);
      location.href='/intervals?date='+dateInput.value;
    }catch(error){output.textContent=error.message;}
  };
  const requireDate=()=>{
    if(!dateInput.value){output.textContent='请先选择增量业务日。';return null;}
    return dateInput.value;
  };
  document.querySelector('#intake').addEventListener('click',()=>{
    const d=requireDate();if(!d)return;
    const runId=document.querySelector('#run-id').value.trim();
    if(!runId){output.textContent='请填写已采信批次 run_id（可从 /api/runs 获取）。';return;}
    call(`/api/intervals/${d}/intake`,{run_id:runId});
  });
  document.querySelector('#close').addEventListener('click',()=>{
    const d=requireDate();if(!d)return;call(`/api/intervals/${d}/close`,{});
  });
  document.querySelector('#review').addEventListener('click',()=>{
    const d=requireDate();if(!d)return;
    call(`/api/intervals/${d}/review`,{version:intervalState.version,decision:'已复核'});
  });
  document.querySelector('#reopen-late').addEventListener('click',()=>{
    const d=requireDate();if(!d)return;
    const runId=document.querySelector('#run-id').value.trim();
    if(!runId){output.textContent='晚到补录同样需要新批次 run_id。';return;}
    call(`/api/intervals/${d}/intake`,{run_id:runId});
  });
})();
