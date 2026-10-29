/* Pure display rules. Stored definitions and missing data retain their meaning. */
((root)=>{
  const modules=[
    {id:'market',name:'市场资料',title:'先看手里的市场样本',note:'只描述你有权使用的样本，币种分开统计；不能代表全平台销量或热度。'},
    {id:'strategy',name:'商品定位',title:'把这件商品的重点说清楚',note:'从当前已确认事实选择核心卖点，参考市场样本也不会新增性能承诺。'},
    {id:'content',name:'内容方案',title:'六个方向，比较不同讲法',note:'商品展示、场景分享、细节讲解各两套结构；选择后继续人工核对与制作。'},
    {id:'images',name:'封面图文',title:'用真实画面做封面',note:'素材保持原比例，文字摘自事实原文；缺图时只生成明确标记的代码图示。'},
    {id:'video',name:'视频交接',title:'成片交给客户自行发布',note:'制作、逐镜修改、恢复版本与听审仍在商品工作台。导出不等于审核通过。'},
    {id:'review',name:'表现复盘',title:'冻结自然内容的表现',note:'平台×账户×作品×日，保留观测时间和缺失值。广告报表继续用原广告数据复盘。'},
    {id:'comments',name:'评论与迭代',title:'把反馈变成下一版要验证的问题',note:'评论先作规则候选，人工选择假设后新建待确认项目；所有制作审批重新核对。'}
  ];
  const labels={research:'市场样本',strategy:'商品定位',image_pack:'封面图文',publication_pack:'视频交接包',observation_snapshot:'冻结复盘',comment_insights:'评论候选',hypothesis:'创意假设',iteration:'下一版',comparison:'两轮对照',content_matrix:'内容矩阵',connection:'账户',source:'来源副本',observation_batch:'观测批次'};
  const metric=v=>v===null||v===undefined?'— 未提供':String(v);
  function definitions(text){const out={};for(const line of text.split(/\r?\n/).filter(s=>s.trim())){const i=line.indexOf('｜');if(i<=0||!line.slice(i+1).trim()||Object.hasOwn(out,line.slice(0,i).trim()))throw Error('每行填写“列名｜完整平台口径”，列名不能重复');out[line.slice(0,i).trim()]=line.slice(i+1).trim();}return out;}
  function summary(row){const p=row.payload||{};switch(row.kind){
    case 'research':return '已提供 '+p.sample_count+' 条样本；缺价 '+p.missing_price_rows+' 条，无法据此推断全市场规模。';
    case 'strategy':return (p.positioning?.subject||'商品')+' · '+(p.positioning?.audience||'')+' · 定位草稿待核对';
    case 'image_pack':return p.display_kind==='schematic_not_product_photo'?'代码图示，非商品照片；待审。':'使用本商品提供画面与原文；封面仍待审核。';
    case 'publication_pack':return (p.review_status==='approved_for_manual_handoff'&&p.handoff_review?.approved_for_handoff===true?'成片已审，平台文案待核对':'成片待审')+'；此包不会发布或投放。'+(p.handoff_review?.blockers?.length?' '+p.handoff_review.blockers.join('；'):'');
    case 'observation_snapshot':return (p.counting==='daily'?'每日观测':'累计观测，不作为日增量')+' · '+(p.rows?.length||0)+' 行，未知不补零。';
    case 'comment_insights':return '本机规则候选；保留行级依据，不自动生成商品事实或回复。';
    case 'hypothesis':return '三个待人工选择的创意假设，没有因果结论。';
    case 'iteration':return '已创建待确认下一版；事实、文稿、风格、听核与成片审核待完成。'+(p.warnings?.length?' '+p.warnings.join('；'):'');
    case 'comparison':return p.comparable?'两轮口径可作描述性对照；不能归因于创意改动。':'当前两轮不可比，缺口已保留；不输出效果增幅。';
    case 'content_matrix':return '六方向的主题与素材矩阵草稿；未安排发布。';
    default:return labels[row.kind]||'已保存本机记录';
  }}
  const api={modules,labels,metric,definitions,summary};if(typeof module==='object'&&module.exports)module.exports=api;root.OperationsState=api;
})(typeof window==='object'?window:globalThis);
