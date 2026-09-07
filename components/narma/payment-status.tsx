"use client";
import {useCallback,useEffect,useState} from "react";
type Order={paymentStatus:string;fulfillmentStatus:string;amountKopecks:number};
export default function PaymentStatus({id}:{id:string}) {
  const [order,setOrder]=useState<Order|null>(null),[notice,setNotice]=useState(""),[busy,setBusy]=useState(false);
  const load=useCallback(async(refresh=false)=>{
    setBusy(true);
    try{const response=await fetch(`/api/payments/${id}`,{method:refresh?"POST":"GET"});const body=await response.json() as {order?:Order;error?:string};if(!response.ok||!body.order)throw new Error(body.error??"Статус временно недоступен.");setOrder(body.order);setNotice("");}
    catch(error){setNotice(error instanceof Error?error.message:"Статус временно недоступен.");}finally{setBusy(false);}
  },[id]);
  useEffect(()=>{const timer=setTimeout(()=>void load(),0);return()=>clearTimeout(timer);},[load]);
  const granted=order?.paymentStatus==="succeeded"&&order.fulfillmentStatus==="granted";
  return <div className="payment-result-steps"><p role="status">{order ? granted?"Оплата подтверждена. Лимит начислен в аккаунт.":order.paymentStatus==="canceled"?"Платёж отменён.":order.fulfillmentStatus==="manual_review"?"Заказ на проверке. Обратитесь в поддержку.":"Ожидаем подтверждение оплаты и начисление лимита.":"Загружаем состояние заказа…"}</p>
    {order&&<p>Сумма заказа: {(order.amountKopecks/100).toLocaleString("ru-RU")} ₽</p>}
    {notice&&<p role="alert">{notice}</p>}
    <button type="button" disabled={busy||granted} onClick={()=>void load(true)}>{busy?"Проверяем…":"Проверить оплату"}</button>
  </div>;
}
