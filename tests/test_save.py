"""Browser regression checks: python3 -m unittest discover -s tests -v

Requires Python Playwright and Chromium (CHROMIUM_PATH may override its path).
Native iOS share-sheet behavior still requires an iPhone/iPad check.
No map services or external network requests are needed by this harness.
"""
import os
from pathlib import Path
import unittest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PAGES = ('v3.html', 'photo-map-mobile.html')


def section(source, start, end):
    return source[source.index(start):source.index(end, source.index(start))]


class SaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(
            executable_path=os.environ.get('CHROMIUM_PATH', '/usr/bin/chromium'),
            args=['--no-sandbox'])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def harness(self, name, ios=True):
        context = self.browser.new_context(accept_downloads=True)
        self.addCleanup(context.close)
        page = context.new_page()
        page.set_default_timeout(5000)
        page.route('**/*', lambda route: route.fulfill(body='<!doctype html><body></body>', content_type='text/html'))
        page.goto('http://localhost/save-test')
        source = (ROOT / name).read_text()
        page.add_script_tag(content=section(source, 'function isIOS()', '// exifr'))
        page.add_script_tag(content=section(source, 'var db = null;', 'function idbDel('))
        page.add_script_tag(content=section(source, 'async function saveSurvey()', 'function mkSurveyMkr('))
        page.add_script_tag(content=section(source, 'async function pmSave(', '// ══ SURVEY FORM'))
        page.evaluate('''ios => {
          Object.defineProperty(navigator,'userAgent',{value:ios?'iPhone':'Android',configurable:true});
          window.calls=[];window.messages=[];window.closed=0;window.result='pending';
          window.toast=m=>messages.push(m);window.closeAll=()=>closed++;
          window.updCounts=()=>{};window.surveys=[];window.photos=[];window.draft={};
          window.shareError=null;
          Object.defineProperty(navigator,'canShare',{configurable:true,value:()=>true});
          Object.defineProperty(navigator,'share',{configurable:true,value:data=>{
            if(!navigator.userActivation.isActive)throw new DOMException('User activation required','NotAllowedError');
            calls.push(data.files.map(f=>({name:f.name,type:f.type,size:f.size})));
            return shareError?Promise.reject(new DOMException('Test failure',shareError)):Promise.resolve();
          }});
        }''', ios)
        return page

    def start_save(self, page, filename='사진.jpg'):
        page.evaluate('''name=>{shareOrDownload(new Blob(['payload'],{type:'image/jpeg'}),name,'현장 기록').then(v=>result=v);}''', filename)

    def test_delayed_ios_share_requires_a_fresh_tap(self):
        for name in PAGES:
            with self.subTest(page=name):
                page = self.harness(name)
                self.start_save(page)
                self.assertEqual(page.evaluate('calls.length'), 0)
                self.assertEqual(page.evaluate('result'), 'pending')
                page.get_by_role('button', name='공유 / 파일에 저장').click()
                page.wait_for_function('result === true')
                self.assertEqual(page.evaluate('calls[0][0].name'), '사진.jpg')
                self.assertEqual(page.locator('dialog').count(), 0)

    def test_cancel_and_permission_error_preserve_files_for_retry(self):
        for name in PAGES:
            for error in ('AbortError', 'NotAllowedError'):
                with self.subTest(page=name, error=error):
                    page = self.harness(name)
                    page.evaluate('e=>shareError=e', error)
                    self.start_save(page)
                    page.get_by_role('button', name='공유 / 파일에 저장').click()
                    page.wait_for_function('document.querySelector("[role=status]").textContent.includes("취소") || document.querySelector("[role=status]").textContent.includes("열지 못")')
                    self.assertEqual(page.evaluate('result'), 'pending')
                    self.assertEqual(page.evaluate('calls.length'), 1)
                    self.assertEqual(page.locator('dialog a').count(), 1)
                    page.evaluate('shareError=null')
                    page.get_by_role('button', name='공유 / 파일에 저장').click()
                    page.wait_for_function('result === true')

    def test_dismiss_reports_false(self):
        for name in PAGES:
            with self.subTest(page=name):
                page = self.harness(name)
                self.start_save(page)
                page.get_by_role('button', name='닫기', exact=True).click()
                page.wait_for_function('result === false')
                self.assertEqual(page.evaluate('calls.length'), 0)

    def test_unsupported_mixed_files_need_manual_download_and_confirmation(self):
        for name in PAGES:
            with self.subTest(page=name):
                page = self.harness(name)
                page.evaluate('''() => {
                  Object.defineProperty(navigator,'canShare',{value:()=>false});
                  savePreparedFiles([new File(['photo'],'사진.jpg',{type:'image/jpeg'}),
                    new File(['note'],'기록.csv',{type:'text/csv'})],'기록').then(v=>result=v);
                }''')
                confirm = page.get_by_role('button', name='모든 파일 저장을 마쳤습니다')
                self.assertTrue(confirm.is_disabled())
                self.assertTrue(page.get_by_role('button', name='공유 / 파일에 저장', include_hidden=True).is_hidden())
                for i, filename in enumerate(('사진.jpg', '기록.csv')):
                    with page.expect_download() as info:
                        page.locator('dialog a').nth(i).click()
                    self.assertEqual(info.value.suggested_filename, filename)
                    self.assertEqual(page.evaluate('result'), 'pending')
                confirm.click()
                page.wait_for_function('result === true')
                self.assertEqual(page.evaluate('calls.length'), 0)

    def test_zip_mime_and_android_direct_download(self):
        for name in PAGES:
            with self.subTest(page=name):
                page = self.harness(name)
                self.start_save(page, '지역.zip')
                page.get_by_role('button', name='공유 / 파일에 저장').click()
                page.wait_for_function('result === true')
                self.assertEqual(page.evaluate('calls[0][0].type'), 'application/zip')
                android = self.harness(name, ios=False)
                with android.expect_download() as info:
                    self.start_save(android)
                self.assertEqual(info.value.suggested_filename, '사진.jpg')
                self.assertEqual(Path(info.value.path()).read_bytes(), b'payload')
                self.assertEqual(android.locator('dialog').count(), 0)
                self.assertEqual(android.evaluate('calls.length'), 0)

    def test_survey_persists_and_failed_write_keeps_form(self):
        for name in PAGES:
            with self.subTest(page=name):
                page = self.harness(name)
                page.evaluate('''() => {
                  document.body.innerHTML='<input id="sfTitle" value="현장 조사"><textarea id="sfNote">메모</textarea>';
                }''')
                page.evaluate('saveSurvey()')
                self.assertEqual(page.evaluate('surveys.length'), 1)
                page.evaluate('db.close();db=null')
                records = page.evaluate('idbAll("surveys")')
                self.assertEqual(records[0]['note'], '메모')
                page.evaluate('''() => {
                  surveys=[];closed=0;messages=[];
                  openDB=()=>Promise.reject(new DOMException('Unavailable','SecurityError'));
                }''')
                page.evaluate('saveSurvey()')
                self.assertEqual(page.evaluate('surveys.length'), 0)
                self.assertEqual(page.evaluate('closed'), 0)
                self.assertEqual(page.locator('#sfTitle').input_value(), '현장 조사')
                self.assertIn('저장하지 못했습니다', page.evaluate('messages[0]'))

    def test_transaction_abort_and_photo_save_failure_are_not_success(self):
        for name in PAGES:
            with self.subTest(page=name):
                page = self.harness(name)
                page.evaluate('''() => {
                  openDB=()=>Promise.resolve({transaction(){
                    const tx={objectStore(){return {put(){queueMicrotask(()=>tx.onabort());}}}};
                    return tx;
                  }});
                  document.body.innerHTML='<input id="pmTitle" value="현장 사진"><button id="pmSave">저장</button>';
                  window.pmDraft={dataUrl:'image',cats:[],rating:0};window.pmTags=[];
                  window.compressImage=async x=>x;window.makeThumb=async x=>x;
                  window.photoRecord=p=>p;
                }''')
                self.assertFalse(page.evaluate('idbPut("photos",{id:"test"})'))
                page.evaluate('pmSave()')
                self.assertEqual(page.evaluate('photos.length'), 0)
                self.assertEqual(page.evaluate('closed'), 0)
                self.assertFalse(page.locator('#pmSave').is_disabled())
                self.assertIn('저장 실패', page.evaluate('messages.at(-1)'))
                self.assertEqual(page.locator('#pmTitle').input_value(), '현장 사진')

    def test_non_jpeg_export_is_really_converted(self):
        for name in PAGES:
            with self.subTest(page=name):
                page = self.harness(name)
                source = (ROOT / name).read_text()
                page.add_script_tag(content=section(source, 'async function exportJPEG(', 'async function _photoToFile('))
                for fn in ['_photoToFile', 'buildXMPPacket', 'injectXMPIntoJPEG', 'dataUrlToBlob']:
                    start = source.index('function '+fn+'(')
                    if source[start-6:start] == 'async ':
                        start -= 6
                    page.add_script_tag(content=source[start:source.index('\n}', start)+2])
                result = page.evaluate('''async () => {
                  const canvas=document.createElement('canvas');canvas.width=8;canvas.height=8;
                  const ctx=canvas.getContext('2d');ctx.fillStyle='red';ctx.fillRect(0,0,8,8);
                  const png=await new Promise(r=>canvas.toBlob(r,'image/png'));
                  window._tsFromId=()=> '20261007_120000';
                  window.exportImageBlob=async()=>png;
                  const exported=await _photoToFile({id:'p1',name:'사진',desc:'현장 메모',dataUrl:canvas.toDataURL('image/png')});
                  if(exported.type!=='image/jpeg' || !exported.name.endsWith('.jpg'))throw new Error('Wrong file type');
                  const decoded=await createImageBitmap(exported);
                  if(decoded.width!==8 || decoded.height!==8)throw new Error('Invalid JPEG pixels');
                  decoded.close();
                  if(!(await exported.text()).includes('현장 메모'))throw new Error('Missing XMP note');
                  const jpeg=await exportJPEG(png);
                  const signature=Array.from(new Uint8Array(await jpeg.slice(0,2).arrayBuffer()));
                  const unchanged=await exportJPEG(jpeg);
                  let badRejected=false;
                  try{await exportJPEG(new Blob(['not an image'],{type:'image/jpeg'}));}catch(e){badRejected=true;}
                  return {type:jpeg.type,signature,unchanged:unchanged===jpeg,badRejected};
                }''')
                self.assertEqual(result, {'type': 'image/jpeg', 'signature': [255, 216], 'unchanged': True, 'badRejected': True})

    @unittest.skipUnless(os.environ.get('JSZIP_PATH'), 'Set JSZIP_PATH to JSZip 3.10.1 for real ZIP checks')
    def test_bulk_export_over_five_files_is_one_zip_without_name_collisions(self):
        for name in PAGES:
            with self.subTest(page=name):
                page = self.harness(name)
                page.add_script_tag(path=os.environ['JSZIP_PATH'])
                page.evaluate('''() => {
                  Object.defineProperty(navigator,'share',{value:data=>{
                    if(!navigator.userActivation.isActive)throw new DOMException('Activation','NotAllowedError');
                    window.sharedFiles=data.files;return Promise.resolve();
                  }});
                  const files=Array.from({length:12},(_,i)=>new File(['photo-'+i],'same.jpg',{type:'image/jpeg'}));
                  files.push(new File(['현재 메모'],'노트.txt',{type:'text/plain'}));
                  saveExportFiles(files,'일괄 저장','기록.zip').then(v=>result=v);
                }''')
                page.get_by_role('button', name='공유 / 파일에 저장').click()
                page.wait_for_function('result === true')
                result = page.evaluate('''async () => {
                  const file=sharedFiles[0],zip=await JSZip.loadAsync(await file.arrayBuffer());
                  const entries=Object.values(zip.files).filter(f=>!f.dir);
                  return {count:sharedFiles.length,name:file.name,type:file.type,
                    contents:await Promise.all(entries.map(f=>f.async('string')))};
                }''')
                self.assertEqual(result['count'], 1)
                self.assertEqual(result['name'], '기록.zip')
                self.assertEqual(result['type'], 'application/zip')
                self.assertCountEqual(result['contents'], ['photo-'+str(i) for i in range(12)] + ['현재 메모'])

    @unittest.skipUnless(os.environ.get('JSZIP_PATH'), 'Set JSZIP_PATH to JSZip 3.10.1 for real ZIP checks')
    def test_region_zip_preserves_twenty_photos_and_current_element_notes(self):
        source = (ROOT / 'v3.html').read_text()
        def function(name):
            start = source.index('function '+name+'(')
            if source[start-6:start] == 'async ':
                start -= 6
            return source[start:source.index('\n}', start)+2]
        for prefix, export_name, region in [('ami', 'exportAmiReviews', 'busan-ami'), ('hs', 'exportHsReviews', 'changwon-hapseong')]:
            with self.subTest(region=region):
                page = self.harness('v3.html')
                page.add_script_tag(path=os.environ['JSZIP_PATH'])
                helpers = ['idbGet', 'dataUrlToBlob', 'reviewExportReadPhotos', 'reviewExportPhotoBlob',
                           prefix+'PhotoMatches', prefix+'ExportSnapshot', prefix+'ExportCSV',
                           prefix+'ExportDocuments', prefix+'ExportExtension', export_name]
                page.add_script_tag(content='\n'.join(function(f) for f in helpers))
                page.evaluate('''async ({prefix,region}) => {
                  window._origFiles={};window.pb=()=>{};
                  window[prefix+'ExportBusy']=false;window.hsExportURL=null;
                  window[prefix+'ExportReadPhotos']=reviewExportReadPhotos;
                  window[prefix+'ExportZipLibrary']=exportZipLibrary;
                  window[prefix.toUpperCase()+'_REVIEW_PREFIX']='review:';
                  window[prefix.toUpperCase()+'_REVIEW_STATUSES']=['미확인','반영','미반영'];
                  window[prefix+'ExportTargets']=()=>[
                    {key:'element:1',title:'첫 번째 요소',lat:35,lng:128},
                    {key:'element:2',title:'두 번째 요소',lat:35,lng:128}];
                  localStorage.setItem('review:element:1',JSON.stringify({memo:'최신 현장 노트',status:'반영'}));
                  localStorage.setItem('review:element:2',JSON.stringify({memo:'사진 없는 요소의 노트',status:'미반영'}));
                  const bytes=new Uint8Array(1024*1024);bytes[0]=255;bytes[1]=216;
                  for(let i=0;i<20;i++){
                    bytes[bytes.length-1]=i;
                    const rec={id:'p'+i,name:'현장 사진 '+i,memo:'촬영 당시 메모',date:'2026-10-07',lat:35,lng:128};
                    rec[prefix+'TargetKey']='element:1';
                    if(i===19)rec.dataUrl='data:image/jpeg;base64,/9j/2Q==';
                    else rec.origBlob=new Blob([bytes],{type:'image/jpeg'});
                    await requireIDBPut('photos',rec);
                  }
                  await requireIDBPut('photos',{id:'unrelated',amiTargetKey:'elsewhere',origBlob:new Blob(['unrelated'])});
                  window.metadata=await reviewExportReadPhotos();
                  Object.defineProperty(navigator,'share',{value:data=>{
                    if(!navigator.userActivation.isActive)throw new DOMException('Activation','NotAllowedError');
                    window.sharedFiles=data.files;return Promise.resolve();
                  }});
                  document.body.innerHTML='<div class="lp-grp"><button id="export">내보내기</button></div>';
                }''', {'prefix': prefix, 'region': region})
                self.assertTrue(page.evaluate('metadata.every(p=>!("origBlob" in p)&&!("dataUrl" in p))'))
                page.evaluate('name=>{window.exportDone=false;window[name](document.querySelector("#export")).then(()=>exportDone=true);}', export_name)
                page.get_by_role('button', name='공유 / 파일에 저장').click(timeout=30000)
                page.wait_for_function('exportDone')
                result = page.evaluate('''async () => {
                  const zip=await JSZip.loadAsync(await sharedFiles[0].arrayBuffer());
                  const doc=JSON.parse(await zip.file('전체기록.json').async('string'));
                  const pictures=Object.keys(zip.files).filter(n=>n.startsWith('사진/')&&!zip.files[n].dir);
                  return {files:sharedFiles.length,type:sharedFiles[0].type,pictures:pictures.length,
                    doc, csv:await zip.file('대상지_입력정보.csv').async('string'),
                    contents:await Promise.all(pictures.map(async n=>{
                      const data=await zip.file(n).async('uint8array');return {length:data.length,last:data[data.length-1]};
                    }))};
                }''')
                self.assertEqual(result['files'], 1)
                self.assertEqual(result['type'], 'application/zip')
                self.assertEqual(result['pictures'], 20)
                self.assertEqual(result['doc']['regionId'], region)
                self.assertEqual(len(result['doc']['photos']), 20)
                self.assertEqual(result['doc']['records'][0]['memo'], '최신 현장 노트')
                self.assertEqual(result['doc']['records'][1]['memo'], '사진 없는 요소의 노트')
                self.assertIn('최신 현장 노트', result['csv'])
                self.assertEqual(len(result['doc']['records'][0]['photos']), 20)
                self.assertEqual(sum(x['length']==1024*1024 for x in result['contents']), 19)
                self.assertCountEqual([x['last'] for x in result['contents'] if x['length']==1024*1024], list(range(19)))
                self.assertEqual(page.evaluate('async () => (await idbAll("photos")).length'), 21)


if __name__ == '__main__':
    unittest.main()
