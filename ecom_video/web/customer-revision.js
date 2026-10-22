/* Review/impact wording shared by the existing workbench. No provider calls. */
(() => {
  function changeNotice(kind) {
    if(kind==='script') return '修改文稿会使全部文稿确认失效；需重新核对事实对应、配音、字幕和分镜，再完成听核及成片审核。旧版保留。';
    if(kind==='voice') return '更换声音或单句重做可能改变时长，后续字幕与镜头位置可能移动；请先查看配音版本差异，再重新听核和审片。';
    if(kind==='global') return '整体风格、音乐或转场变化可能影响全部镜头；请逐镜检查后重新确认风格及成片。';
    return '只改画面且镜长、声音、字幕和全局样式保持时，可复用其他镜头。实际范围以预告及渲染清单为准。';
  }
  function reviewSummary(s) {
    if(!s?.enabled) return '逐镜检查尚未开始。记录首条意见后，所有镜头通过才能放行本版成片。';
    if(!s.all_passed) return '仍有待检查或需修改的镜头，不能通过最终成片审核。';
    return s.fixture ? '工程模拟检查已完成，不作为客户听审或签收。' : '逐镜检查完成，仍需整片看听及成片审核。';
  }
  window.CustomerRevision={changeNotice,reviewSummary};
})();
