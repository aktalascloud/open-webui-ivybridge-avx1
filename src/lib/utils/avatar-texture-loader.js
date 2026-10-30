// Preserve original VRM files; bound decoded GPU textures on each device.
export function textureResizePlan(images,budget=32*1024*1024,maxEdge=4096) {
  if(images.some(i=>!Number.isFinite(i.width)||!Number.isFinite(i.height)||i.width<1||i.height<1))throw Error('Invalid texture dimensions');
  const total=images.reduce((sum,i)=>sum+i.width*i.height,0);
  const scale=Math.min(1,Math.sqrt(budget/Math.max(1,total)));
  return images.map(i=>{const s=Math.min(scale,maxEdge/Math.max(i.width,i.height));return {width:Math.max(1,Math.floor(i.width*s)),height:Math.max(1,Math.floor(i.height*s))};});
}

export function boundedBitmapLoader(images) {
  const plans=textureResizePlan(images),bySize=new Map();
  images.forEach((image,index)=>{const list=bySize.get(image.data.byteLength)||[];list.push({image,plan:plans[index]});bySize.set(image.data.byteLength,list);});
  async function decode(url) {
    if(!url.startsWith('blob:'))throw Error('External textures are blocked');
    const response=await fetch(url),data=new Uint8Array(await response.arrayBuffer());
    const item=(bySize.get(data.byteLength)||[]).find(({image})=>data.every((byte,index)=>byte===image.data[index]));
    if(!item)throw Error('Texture was not validated');
    return createImageBitmap(new Blob([data]),{resizeWidth:item.plan.width,resizeHeight:item.plan.height,resizeQuality:'high',premultiplyAlpha:'none',colorSpaceConversion:'none'});
  }
  return {isImageBitmapLoader:true,load(url,onLoad,_progress,onError){decode(url).then(onLoad,onError);}};
}
