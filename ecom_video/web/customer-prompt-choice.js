/* A library choice is a pending edit, never a save, render or approval. */
(function(root){
'use strict';
function pending(params,project,adaptation){
 const job=project?.job,shot=job?.storyboard?.shots.find(s=>s.shot_id===params.get('shot'));
 if(!adaptation.ready||!shot||project.id!==params.get('project')||job.id!==params.get('job')||
    String(project.revision)!==params.get('revision')||String(job.storyboard_revision)!==params.get('board')||
    adaptation.project_id!==project.id||adaptation.job_id!==job.id||adaptation.revision!==project.revision||adaptation.board_revision!==job.storyboard_revision||adaptation.shot_id!==shot.shot_id)
  throw Error('项目或分镜版本已变化，请从当前这一镜重新打开参考库。未应用任何修改。');
 const choice=adaptation.choices.find(c=>c.id===params.get('prompt'));
 if(!choice)throw Error('此 Prompt 还不能执行，请选择已适配的变体。');
 return {shot_id:shot.shot_id,changes:{shot_recipe:choice.recipe,motion_plan:{version:2,strength:'balanced',cue_offset:0,protect_action:true,windows:[],repeat_limit:2,intent:'auto',...(shot.motion_plan||{}),prompt_card:choice.id}}};
}
if(typeof module!=='undefined')module.exports={pending};
else root.CustomerPromptChoice={pending};
})(typeof window==='undefined'?globalThis:window);
