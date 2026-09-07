import {requireChatGPTUser} from "@/app/chatgpt-auth";
import {getOrCreateCurrentAccount} from "@/lib/auth/current-account";
import VideoWorkspace from "@/components/narma/video-workspace";
export const dynamic="force-dynamic";
export const metadata={title:"Разбор видео",description:"Покадровый разбор игровых видео Dota 2."};
export default async function Videos(){const user=await requireChatGPTUser("/videos");await getOrCreateCurrentAccount(user);return <VideoWorkspace/>;}
