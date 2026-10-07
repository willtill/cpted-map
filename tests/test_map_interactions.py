"""Full-page map checks with real Leaflet. Set MAP_ASSET_DIR to a directory
containing leaflet.js (1.9.3), leaflet.css and leaflet-rotate.js (0.2.8).
External tiles/services are blocked; test hooks are injected only into test HTML.
"""
import os
from pathlib import Path
import unittest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get('MAP_ASSET_DIR'), 'Set MAP_ASSET_DIR for real Leaflet tests')
class MapInteractions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH', '/usr/bin/chromium'), args=['--no-sandbox'])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def app(self, name):
        context = self.browser.new_context(viewport={'width': 430, 'height': 900}, has_touch=True)
        self.addCleanup(context.close)
        page = context.new_page()
        page.set_default_timeout(5000)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        html = (ROOT / name).read_text().replace('})(); // end IIFE', '''
window.__mapTest={map:map,layers:LAYERS,setLoc:setLoc,addMkr:addMkr,photos:photos,
  openLayerSheet:openLayerSheet,closeAll:closeAll,applyVis:applyVis,
  exportCount:_expCount,saveLayers:saveLayers,requireIDBPut:requireIDBPut,mapPickCandidates:mapPickCandidates};
})(); // end IIFE''')
        def route(request):
            url = request.request.url
            if url.startswith('http://localhost/'):
                request.fulfill(body=html, content_type='text/html')
            elif 'cdn.jsdelivr.net' in url and url.split('/')[-1] in ('leaflet.js', 'leaflet.css', 'leaflet-rotate.js'):
                asset = Path(os.environ['MAP_ASSET_DIR']) / url.split('/')[-1]
                request.fulfill(body=asset.read_bytes(), content_type='text/css' if asset.suffix == '.css' else 'application/javascript')
            else:
                request.abort()
        page.route('**/*', route)
        page.goto('http://localhost/'+name, wait_until='networkidle')
        page.wait_for_function('window.__mapTest && !document.getElementById("ni-layer").disabled')
        self.assertEqual(errors, [])
        page.evaluate('''() => {
          const t=__mapTest;t.map.setView([0,0],18,{animate:false});t.closeAll();
          window.picked=[];
          window.testLayer=(id,layer,label)=>{
            t.layers[id]={id,name:label,visible:true,opacity:1,sz:1,mkrs:[],cnt:0};
            layer._pickLabel=label;layer.on('click',()=>picked.push(label));
            layer.addTo(t.map);t.addMkr(id,layer);return layer;
          };
        }''')
        return page, errors

    def test_location_display_does_not_block_point_taps(self):
        for name in ('v3.html', 'photo-map-mobile.html'):
            with self.subTest(page=name):
                page, errors = self.app(name)
                page.evaluate('''() => {
                  testLayer('testPoint',L.marker([0,0],{icon:L.divIcon({className:'test-point',html:'P',iconSize:[30,30],iconAnchor:[15,15]})}),'포인트');
                  __mapTest.setLoc(0,0,50);
                }''')
                point = page.evaluate('__mapTest.map.latLngToContainerPoint([0,0])')
                page.touchscreen.tap(point['x'], point['y'])
                self.assertEqual(page.evaluate('picked'), ['포인트'])
                self.assertEqual(page.locator('.map-pick-item').count(), 0)
                self.assertEqual(page.locator('.location-display-only').evaluate('(e)=>getComputedStyle(e).pointerEvents'), 'none')
                self.assertEqual(errors, [])

    def test_overlapping_lines_offer_each_element_at_any_bearing(self):
        for name in ('v3.html', 'photo-map-mobile.html'):
            with self.subTest(page=name):
                page, errors = self.app(name)
                page.evaluate('''() => {
                  testLayer('testA',L.polyline([[0,-.001],[0,.001]],{weight:3}),'안심라인 #1');
                  testLayer('testB',L.polyline([[0,-.001],[0,.001]],{weight:3}),'안전펜스 #2');
                  const hidden=testLayer('testHidden',L.polyline([[0,-.001],[0,.001]]),'숨긴 선');
                  __mapTest.layers.testHidden.visible=false;__mapTest.applyVis('testHidden');
                  const band=testLayer('testBand',L.polyline([[0,-.001],[0,.001]],{interactive:false}),'장식선');
                }''')
                for index, bearing in enumerate((0, 47, 120)):
                    page.evaluate('b=>{__mapTest.map.setBearing(b);__mapTest.closeAll();}', bearing)
                    point = page.evaluate('__mapTest.map.latLngToContainerPoint([0,0])')
                    page.touchscreen.tap(point['x'], point['y'])
                    self.assertEqual(page.locator('.map-pick-item').count(), 2)
                    self.assertEqual(page.evaluate('picked.length'), index)
                    page.get_by_role('button', name='안전펜스 #2', exact=False).click()
                    self.assertEqual(page.evaluate('picked.at(-1)'), '안전펜스 #2')
                self.assertEqual(errors, [])

    def test_photo_visibility_survives_reload_and_keeps_records(self):
        for name in ('v3.html', 'photo-map-mobile.html'):
            with self.subTest(page=name):
                page, errors = self.app(name)
                page.evaluate('''async () => {
                  const canvas=document.createElement('canvas');canvas.width=canvas.height=10;
                  await __mapTest.requireIDBPut('photos',{id:'p123',name:'보관 사진',lat:35,lng:128,
                    dataUrl:canvas.toDataURL(),thumb:canvas.toDataURL(),date:'2026-10-07'});
                }''')
                page.reload(wait_until='networkidle')
                page.wait_for_function('__mapTest.photos.length===1')
                self.assertEqual(page.evaluate('__mapTest.layers.photo.mkrs.length'), 1)
                page.evaluate('__mapTest.openLayerSheet()')
                switch = page.get_by_role('switch', name='현장 사진 지도에 표시', exact=True)
                self.assertEqual(switch.get_attribute('aria-checked'), 'true')
                switch.click()
                self.assertEqual(page.get_by_role('switch', name='현장 사진 지도에 표시').get_attribute('aria-checked'), 'false')
                self.assertTrue(page.evaluate('__mapTest.layers.photo.mkrs.every(m=>!__mapTest.map.hasLayer(m))'))
                page.reload(wait_until='networkidle')
                page.wait_for_function('__mapTest.photos.length===1')
                self.assertEqual(page.evaluate('__mapTest.layers.photo.mkrs.length'), 1)
                self.assertFalse(page.evaluate('__mapTest.layers.photo.visible'))
                page.evaluate('__mapTest.openLayerSheet()')
                page.get_by_role('switch', name='현장 사진 지도에 표시').click()
                page.evaluate('__mapTest.map.setView([35,128],18,{animate:false});__mapTest.applyVis("photo")')
                self.assertTrue(page.evaluate('__mapTest.layers.photo.mkrs.every(m=>__mapTest.map.hasLayer(m))'))
                self.assertEqual(page.evaluate('__mapTest.photos.length'), 1)
                self.assertEqual(errors, [])

    def test_map_photo_button_syncs_without_changing_records_or_selection(self):
        for name in ('v3.html', 'photo-map-mobile.html'):
            with self.subTest(page=name):
                page, errors = self.app(name)
                button = page.get_by_role('button', name='현장사진 지도 표시', exact=True)
                self.assertEqual(button.get_attribute('aria-pressed'), 'true')
                # The action is available on the map without opening any tab.
                page.set_viewport_size({'width': 360, 'height': 640})
                box = button.bounding_box()
                self.assertGreater(box['x'], 280)
                self.assertGreaterEqual(box['y'], 0)
                self.assertGreaterEqual(box['width'], 44)
                self.assertGreaterEqual(box['height'], 44)
                self.assertLess(box['y']+box['height'], 640)
                button.tap()
                self.assertEqual(button.get_attribute('aria-pressed'), 'false')
                self.assertEqual(button.inner_text(), '사진 표시')
                self.assertFalse(page.locator('#sheet').evaluate('(e)=>e.classList.contains("on")'))
                page.evaluate('''async () => {
                  const canvas=document.createElement('canvas');canvas.width=canvas.height=10;
                  await __mapTest.requireIDBPut('photos',{id:'p123',name:'사진 표시 검사',lat:35,lng:128,
                    dataUrl:canvas.toDataURL(),thumb:canvas.toDataURL(),date:'2026-10-07'});
                }''')
                page.reload(wait_until='networkidle')
                page.wait_for_function('__mapTest.photos.length===1')
                self.assertEqual(page.evaluate('__mapTest.layers.photo.mkrs.length'), 1)
                self.assertEqual(button.get_attribute('aria-pressed'), 'false')
                page.evaluate('__mapTest.map.setView([35,128],18,{animate:false});__mapTest.applyVis("photo")')
                self.assertTrue(page.evaluate('__mapTest.layers.photo.mkrs.every(m=>!__mapTest.map.hasLayer(m))'))
                button.tap()
                self.assertEqual(button.get_attribute('aria-pressed'), 'true')
                self.assertEqual(button.inner_text(), '사진 숨김')
                self.assertTrue(page.evaluate('__mapTest.layers.photo.mkrs.every(m=>__mapTest.map.hasLayer(m))'))
                page.locator('#ni-survey').click()
                self.assertEqual(page.get_by_role('switch', name='현장사진 지도 표시', exact=True).count(), 0)
                page.locator('.sl-chk[data-id="p123"]').click()
                self.assertEqual(page.evaluate('__mapTest.exportCount()'), 1)
                page.locator('#shX').click()
                button.tap()
                self.assertTrue(page.evaluate('__mapTest.layers.photo.mkrs.every(m=>!__mapTest.map.hasLayer(m))'))
                self.assertEqual(page.evaluate('__mapTest.exportCount()'), 1)
                self.assertEqual(page.evaluate('__mapTest.photos[0].name'), '사진 표시 검사')
                page.evaluate('__mapTest.openLayerSheet()')
                layer_switch = page.get_by_role('switch', name='현장 사진 지도에 표시', exact=True)
                self.assertEqual(layer_switch.get_attribute('aria-checked'), 'false')
                layer_switch.click()
                self.assertEqual(button.get_attribute('aria-pressed'), 'true')
                self.assertTrue(page.evaluate('__mapTest.layers.photo.mkrs.every(m=>__mapTest.map.hasLayer(m))'))
                page.locator('#shX').click()
                button.tap()
                page.reload(wait_until='networkidle')
                page.wait_for_function('__mapTest.photos.length===1')
                self.assertEqual(button.get_attribute('aria-pressed'), 'false')
                self.assertEqual(page.evaluate('__mapTest.photos.length'), 1)
                self.assertEqual(errors, [])

    def test_polygon_holes_and_duplicate_feature_parts(self):
        page, errors = self.app('v3.html')
        page.evaluate('''() => {
          const outer=[[-.002,-.002],[-.002,.002],[.002,.002],[.002,-.002]];
          const hole=[[-.001,-.001],[-.001,.001],[.001,.001],[.001,-.001]];
          testLayer('testHole',L.polygon([outer,hole]),'구멍 있는 면');
          const a=testLayer('testA',L.polyline([[0,-.001],[0,.001]]),'요소 A');a._pickKey='same-feature';
          const b=testLayer('testB',L.polyline([[0,-.001],[0,.001]]),'요소 A 다른 부분');b._pickKey='same-feature';
        }''')
        candidates = page.evaluate('''() => {
          const p=__mapTest.map.latLngToContainerPoint([0,0]);
          return __mapTest.mapPickCandidates(p,{x:p.x,y:p.y}).map(x=>x.label);
        }''')
        self.assertEqual(candidates, ['요소 A'])
        self.assertEqual(errors, [])
