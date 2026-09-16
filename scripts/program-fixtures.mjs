// Additional API surfaces for existing offline browser regression suites.
export async function programFixture(route){
  const endpoint=new URL(route.request().url()).pathname;
  let body;
  if(endpoint==='/api/program')body={focus:null,choices:[],review:null,check_candidates:[],stage:'upload',focus_needs_review:false,jobs:[],latest_report:null};
  else if(endpoint==='/api/billing')body={mode:'off',checkout_enabled:false,balance:0,held:0,orders:[],refunds:[],products:[],seller:'',support_email:''};
  else if(endpoint==='/api/billing/refunds')body={refunds:[]};
  else if(endpoint==='/api/explore/updates')body={latest_patch:null,stale:true};
  else return false;
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});return true;
}
