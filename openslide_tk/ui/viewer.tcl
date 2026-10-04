package require Tk
if {[package vcompare [package provide Tk] 8.6] < 0} {error "Tcl/Tk 8.6 or newer is required"}
namespace eval ::os {
    variable width 1920
    variable height 1080
    variable elements {}
    variable following {}
    variable images {}
    variable background #ffffff
    variable next_background #ffffff
    variable index 1
    variable total 1
    variable title "Open Slide"
    variable notes ""
    variable next_title ""
    variable fullscreen 0
    variable started [clock seconds]
    variable selected ""
    variable render_timer ""
    variable fidelity ""
    variable source_slide ""
    variable selected_json ""
    variable form
    variable raster_images {}
    variable raster_pending {}
    variable raster_bad {}
    variable raster_order {}
    variable raster_pixels 0
}

proc ::os::fidelity {message} {variable fidelity $message}

proc ::os::emit {event args} {
    set fields [list $event]
    foreach value $args { lappend fields [binary encode hex [encoding convertto utf-8 $value]] }
    puts [join $fields "\t"]
    flush stdout
}

proc ::os::receive {} {
    if {[eof stdin]} {exit}
    if {[gets stdin line] >= 0 && $line ne ""} {
        if {[catch {uplevel #0 $line} error]} {::os::emit error $error}
    }
}

proc ::os::value {element key fallback} {
    if {[dict exists $element $key]} { return [dict get $element $key] }
    return $fallback
}

proc ::os::notes_font {family} {set ::os::notes_family $family}
set ::os::notes_family Arial

proc ::os::begin {w h bg deck n count slide note} {
    variable fidelity
    variable width $w
    variable height $h
    variable background $bg
    variable elements {}
    variable index $n
    variable total $count
    variable title $slide
    variable notes $note
    wm title . "$deck — Python + Tcl/Tk"
    set ::os::page_label "$n / $count"
    .status configure -text "$slide    $fidelity"
    .body.sidebar.count configure -text "$count 張投影片"
    .body.sidebar.actions.delete state [expr {$count == 1 ? "disabled" : "!disabled"}]
    .body.sidebar.order.up state [expr {$n == 1 ? "disabled" : "!disabled"}]
    .body.sidebar.order.down state [expr {$n == $count ? "disabled" : "!disabled"}]
}

proc ::os::element {args} {
    variable elements
    lappend elements [dict create {*}$args]
}

proc ::os::next_begin {background title} {
    variable following {}
    variable next_background $background
    variable next_title $title
}
proc ::os::next_element {args} { variable following; lappend following [dict create {*}$args] }
proc ::os::next_finish {} { if {[winfo exists .presenter]} {::os::presenter_render} }

proc ::os::paint {canvas data background} {
    variable width
    variable height
    variable images
    set cw [winfo width $canvas]
    set ch [winfo height $canvas]
    if {$cw < 2 || $ch < 2} {return}
    set scale [expr {min(double($cw)/$width,double($ch)/$height)}]
    set ox [expr {($cw-$width*$scale)/2}]
    set oy [expr {($ch-$height*$scale)/2}]
    $canvas delete all
    if {[dict exists $images $canvas]} {
        foreach image [dict get $images $canvas] {catch {image delete $image}}
    }
    dict set images $canvas {}
    $canvas create rectangle $ox $oy [expr {$ox+$width*$scale}] [expr {$oy+$height*$scale}] -fill $background -outline "" -tags page
    foreach e $data {
        if {[::os::value $e opacity 1] == 0} {continue}
        set x [expr {$ox+[dict get $e x]*$scale}]
        set y [expr {$oy+[dict get $e y]*$scale}]
        set w [expr {[dict get $e width]*$scale}]
        set h [expr {[dict get $e height]*$scale}]
        set id [dict get $e id]
        set tag [list element "id:$id"]
        set fill [::os::value $e fill ""]
        set stroke [::os::value $e stroke ""]
        set sw [expr {[::os::value $e stroke_width 1]*$scale}]
        switch -- [dict get $e type] {
            rect - ellipse {
                set kind [expr {[dict get $e type] eq "rect" ? "rectangle" : "oval"}]
                $canvas create $kind $x $y [expr {$x+$w}] [expr {$y+$h}] -fill $fill -outline $stroke -width $sw -tags $tag
            }
            line {
                if {$stroke eq ""} {continue}
                $canvas create line $x $y [expr {$x+$w}] [expr {$y+$h}] -fill $stroke -width $sw -tags $tag
            }
            text {
                if {$fill ne "" || $stroke ne ""} {
                    $canvas create rectangle $x $y [expr {$x+$w}] [expr {$y+$h}] -fill $fill -outline $stroke -width $sw -tags $tag
                }
                set family [::os::value $e _display_font_family [::os::value $e font_family Arial]]
                set size [expr {max(1,round([::os::value $e font_size 48]*$scale))}]
                set weight [expr {[::os::value $e bold 0] ? "bold" : "normal"}]
                set align [::os::value $e align left]
                set font [list $family [expr {-$size}] $weight]
                set anchor nw
                if {$align eq "center"} {set x [expr {$x+$w/2}]; set anchor n}
                if {$align eq "right"} {set x [expr {$x+$w}]; set anchor ne}
                $canvas create text $x $y -text [dict get $e text] -font $font -fill [::os::value $e color #172f39] -anchor $anchor -width $w -justify $align -tags $tag
            }
            image {
                set asset [dict get $e path]
                if {[string tolower [file extension $asset]] eq ".png"} {
                    set pw [expr {max(1,round($w))}]
                    set ph [expr {max(1,round($h))}]
                    set stamp "missing"
                    catch {set stamp "[file mtime $asset]:[file size $asset]"}
                    set key [list $asset $stamp $pw $ph]
                    if {[dict exists $::os::raster_images $key]} {
                        $canvas create image $x $y -anchor nw -image [dict get $::os::raster_images $key] -tags $tag
                        if {$stroke ne ""} {$canvas create rectangle $x $y [expr {$x+$w}] [expr {$y+$h}] -fill "" -outline $stroke -width $sw -tags $tag}
                        continue
                    }
                    if {![dict exists $::os::raster_bad $key]} {
                        if {![dict exists $::os::raster_pending $key]} {
                            dict set ::os::raster_pending $key 1
                            ::os::emit image_request $key $asset $pw $ph
                        }
                        $canvas create rectangle $x $y [expr {$x+$w}] [expr {$y+$h}] -fill $background -outline "" -tags $tag
                        $canvas create text [expr {$x+$w/2}] [expr {$y+$h/2}] -anchor center -fill #9bbab2 -font {Arial 13} -text "圖片載入中…" -tags $tag
                        continue
                    }
                    if {[dict get $::os::raster_bad $key] eq "invalid"} {
                        $canvas create text $x $y -anchor nw -width $w -text "圖片無法顯示" -fill #df9e7c -tags $tag
                        continue
                    }
                }
                if {[catch {set src [image create photo -file [dict get $e path]]} reason]} {
                    $canvas create rectangle $x $y [expr {$x+$w}] [expr {$y+$h}] -fill #d8e5e8 -outline #72858a -tags $tag
                    $canvas create text [expr {$x+12}] [expr {$y+12}] -anchor nw -width [expr {max(10,$w-24)}] -text "Image unavailable in Tk: [::os::value $e alt image]" -tags $tag
                } else {
                    set iw [image width $src]
                    set ih [image height $src]
                    set denominator 64
                    set nx [expr {max(1,round($w/$iw*$denominator))}]
                    set ny [expr {max(1,round($h/$ih*$denominator))}]
                    set display [image create photo]
                    $display copy $src -zoom $nx $ny -subsample $denominator $denominator
                    $canvas create image $x $y -anchor nw -image $display -tags $tag
                    if {$stroke ne ""} {$canvas create rectangle $x $y [expr {$x+$w}] [expr {$y+$h}] -fill "" -outline $stroke -width $sw -tags $tag}
                    dict lappend images $canvas $src
                    dict lappend images $canvas $display
                }
            }
        }
    }
}

proc ::os::raster_ready {key encoded} {
    variable raster_images
    variable raster_pending
    variable raster_order
    variable raster_pixels
    if {[dict exists $raster_pending $key]} {dict unset raster_pending $key}
    if {[catch {set photo [image create photo -data $encoded -format png]} error]} {
        ::os::raster_unavailable $key invalid $error
        return
    }
    if {[dict exists $raster_images $key]} {
        set old [dict get $raster_images $key]
        incr raster_pixels [expr {-[image width $old]*[image height $old]}]
        image delete $old
        set position [lsearch -exact $raster_order $key]
        set raster_order [lreplace $raster_order $position $position]
    }
    dict set raster_images $key $photo
    lappend raster_order $key
    incr raster_pixels [expr {[image width $photo]*[image height $photo]}]
    while {[llength $raster_order] > 24 || $raster_pixels > 12000000} {
        set oldest [lindex $raster_order 0]
        set raster_order [lrange $raster_order 1 end]
        set expired [dict get $raster_images $oldest]
        incr raster_pixels [expr {-[image width $expired]*[image height $expired]}]
        image delete $expired
        dict unset raster_images $oldest
    }
    after idle ::os::finish
}

proc ::os::raster_unavailable {key kind message} {
    variable raster_bad
    variable raster_pending
    if {[dict exists $raster_pending $key]} {dict unset raster_pending $key}
    dict set raster_bad $key $kind
    .status configure -text "圖片預覽：$message"
    after idle ::os::finish
}

proc ::os::finish {} {
    variable elements
    variable background
    ::os::paint .body.canvas $elements $background
    ::os::highlight_selection
    if {[winfo exists .presenter]} {::os::presenter_render}
}

proc ::os::schedule_render {} {
    variable render_timer
    if {$render_timer ne ""} {after cancel $render_timer}
    set render_timer [after 40 ::os::finish]
}

proc ::os::catalog {args} {
    variable index
    .body.list delete 0 end
    set n 0
    foreach title $args {incr n; .body.list insert end "$n  $title"}
    .body.list selection set [expr {$index-1}]
    .body.list see [expr {$index-1}]
}

proc ::os::pick {} {
    set selected [.body.list curselection]
    if {[llength $selected]} {::os::emit jump [lindex $selected 0]}
}

proc ::os::hit {x y} {
    set items [.body.canvas find overlapping $x $y $x $y]
    foreach item [lreverse $items] {
        foreach tag [.body.canvas gettags $item] {
            if {[string match "id:*" $tag]} {::os::emit edit [string range $tag 3 end]; return}
        }
    }
}

proc ::os::full {} {
    variable fullscreen
    set fullscreen [expr {!$fullscreen}]
    wm attributes . -fullscreen $fullscreen
    if {$fullscreen} {
        pack forget .toolbar .footer
        pack forget .body.sidebar .body.inspector
    } else {
        pack .toolbar -side top -fill x -before .body
        pack .footer -side bottom -fill x
        pack .body.sidebar -side left -fill y -before .body.canvas
        pack .body.inspector -side right -fill y -before .body.canvas
    }
}

proc ::os::escape {} {
    variable fullscreen
    if {$fullscreen} {::os::full}
}

proc ::os::message {title body} {tk_messageBox -title $title -message $body -type ok}

proc ::os::editor {window title value callback} {
    catch {destroy $window}
    toplevel $window
    wm title $window $title
    wm geometry $window 850x650
    $window configure -background #171d23
    text $window.text -wrap none -font {Courier 13} -undo 1 -background #202830 -foreground #eaf3f0 -insertbackground #92dfc1 -selectbackground #34584f -padx 18 -pady 18 -borderwidth 0 -highlightthickness 0
    $window.text insert 1.0 $value
    ttk::button $window.save -text "儲存" -command [list ::os::save_editor $window $callback]
    pack $window.save -side bottom -pady 12
    pack $window.text -fill both -expand 1
    focus $window.text
}

proc ::os::save_editor {window callback} {
    set value [$window.text get 1.0 end-1c]
    uplevel #0 [list {*}$callback $value]
}
proc ::os::source_editor {value} {::os::editor .source "編輯簡報 JSON" $value {::os::emit save_source}}
proc ::os::highlight_selection {} {
    variable selected
    .body.canvas delete selection
    if {$selected eq "" || $::os::fullscreen} {return}
    set bounds [.body.canvas bbox "id:$selected"]
    if {[llength $bounds] == 4} {
        lassign $bounds x1 y1 x2 y2
        .body.canvas create rectangle [expr {$x1-4}] [expr {$y1-4}] [expr {$x2+4}] [expr {$y2+4}] -outline #7ddbb7 -width 2 -dash {5 3} -tags selection
    }
}

proc ::os::history_state {undo redo} {
    .toolbar.undo state [expr {$undo ? "!disabled" : "disabled"}]
    .toolbar.redo state [expr {$redo ? "!disabled" : "disabled"}]
}

proc ::os::editor_notice {text} {
    .body.inspector.notice configure -text $text
}

proc ::os::form_state {parent state} {
    foreach child [winfo children $parent] {
        if {[winfo class $child] in {TEntry TCombobox TCheckbutton TButton}} {$child state $state}
        ::os::form_state $child $state
    }
}

proc ::os::clear_inspector {} {
    variable selected ""
    variable source_slide ""
    .body.inspector.heading configure -text "元素屬性"
    .body.inspector.detail configure -text "點選畫布上的文字或圖形，即可在這裡編輯。"
    .body.inspector.apply state disabled
    ::os::form_state .body.inspector.tabs disabled
    .body.inspector.tabs.content.text configure -state normal
    .body.inspector.tabs.content.text delete 1.0 end
    .body.inspector.tabs.content.text configure -state disabled
    .body.inspector.tabs.advanced.raw state disabled
    ::os::highlight_selection
}

proc ::os::inspect {slide id source args} {
    variable selected $id
    variable source_slide $slide
    variable selected_json $source
    variable form
    set e [dict create {*}$args]
    ::os::form_state .body.inspector.tabs !disabled
    array unset form
    foreach {key fallback} {x 0 y 0 width 100 height 100 font_family Arial east_asian_font {} font_size 48 color #172F39 fill {} stroke {} stroke_width 1 bold 0 align left text {} alt {}} {
        set form($key) [::os::value $e $key $fallback]
    }
    set form(type) [dict get $e type]
    set form(alignment) [dict get {left 靠左 center 置中 right 靠右} $form(align)]
    set label [dict get {text 文字 rect 矩形 ellipse 橢圓 line 線條 image 圖片} $form(type)]
    .body.inspector.heading configure -text "$label 屬性"
    .body.inspector.detail configure -text "修改後按「套用變更」，立即儲存到本機。"
    set page .body.inspector.tabs.content
    $page.text configure -state normal
    $page.text delete 1.0 end
    if {$form(type) eq "text"} {
        $page.text insert 1.0 $form(text)
        $page.label configure -text "文字內容"
    } elseif {$form(type) eq "image"} {
        $page.text insert 1.0 $form(alt)
        $page.label configure -text "圖片說明"
    } else {
        $page.label configure -text "圖形樣式"
        $page.text insert 1.0 "在下方設定填色與邊框。\n位置和尺寸位於「位置」分頁。"
        $page.text configure -state disabled
    }
    set text_state [expr {$form(type) eq "text" ? "!disabled" : "disabled"}]
    foreach widget [list $page.font.font_family $page.font.east_asian_font $page.font.font_size $page.font.bold $page.font.align $page.colors.color $page.colors.color_choose] {
        $widget state $text_state
    }
    if {$form(type) in {image line}} {
        foreach widget [list $page.colors.fill $page.colors.fill_choose $page.colors.fill_clear] {$widget state disabled}
    }
    .body.inspector.tabs.advanced.identifier configure -text "元素：$id"
    .body.inspector.tabs.advanced.raw state !disabled
    .body.inspector.apply state !disabled
    .body.inspector.notice configure -text "所有變更都可以復原"
    ::os::highlight_selection
}

proc ::os::color_choose {key} {
    variable form
    set initial $form($key)
    if {![regexp {^#[0-9a-fA-F]{6}$} $initial]} {set initial #172F39}
    set value [tk_chooseColor -initialcolor $initial -title "選擇顏色"]
    if {$value ne ""} {set form($key) $value}
}

proc ::os::color_field {parent key label row} {
    ttk::label $parent.${key}_label -text $label
    ttk::entry $parent.$key -textvariable ::os::form($key) -width 11
    ttk::button $parent.${key}_choose -text "色票" -width 4 -command [list ::os::color_choose $key]
    grid $parent.${key}_label -row $row -column 0 -sticky w -pady 4
    grid $parent.$key -row $row -column 1 -sticky ew -padx 7 -pady 4
    grid $parent.${key}_choose -row $row -column 2 -pady 4
    if {$key ne "color"} {
        ttk::button $parent.${key}_clear -text "清除" -width 4 -command [list set ::os::form($key) ""]
        grid $parent.${key}_clear -row $row -column 3 -padx {5 0} -pady 4
    }
    grid columnconfigure $parent 1 -weight 1
}

proc ::os::apply_inspector {} {
    variable form
    variable selected
    variable source_slide
    if {$selected eq ""} {return}
    set fields [list $source_slide $selected]
    foreach key {x y width height fill stroke stroke_width} {lappend fields $key $form($key)}
    if {$form(type) eq "text"} {
        foreach key {font_family east_asian_font font_size color bold} {lappend fields $key $form($key)}
        lappend fields align [dict get {靠左 left 置中 center 靠右 right} $form(alignment)]
        lappend fields text [.body.inspector.tabs.content.text get 1.0 end-1c]
    } elseif {$form(type) eq "image"} {
        lappend fields alt [.body.inspector.tabs.content.text get 1.0 end-1c]
    }
    ::os::emit save_form {*}$fields
}

proc ::os::advanced_element {} {
    variable selected
    variable source_slide
    variable selected_json
    if {$selected ne ""} {
        ::os::editor .raw_element "進階元素資料" $selected_json [list ::os::emit save_element_at $source_slide $selected]
    }
}

proc ::os::scroll_page_width {viewport} {
    $viewport itemconfigure body -width [expr {max(1,[winfo width $viewport])}]
}

proc ::os::scroll_page_region {viewport} {
    $viewport configure -scrollregion [$viewport bbox all]
}

proc ::os::scroll_page_wheel {viewport delta} {
    if {$delta == 0} {return}
    set steps [expr {max(1,abs($delta)/40)}]
    $viewport yview scroll [expr {$delta > 0 ? -$steps : $steps}] units
}

proc ::os::scroll_page {page} {
    canvas $page.viewport -background #202830 -borderwidth 0 -highlightthickness 0 -height 1 -width 1 -yscrollincrement 18
    ttk::scrollbar $page.scrollbar -orient vertical -command [list $page.viewport yview]
    $page.viewport configure -yscrollcommand [list $page.scrollbar set]
    ttk::frame $page.viewport.body
    $page.viewport create window 0 0 -anchor nw -window $page.viewport.body -tags body
    bind $page.viewport <Configure> [list ::os::scroll_page_width $page.viewport]
    bind $page.viewport.body <Configure> [list ::os::scroll_page_region $page.viewport]
    bind $page.viewport <MouseWheel> [list ::os::scroll_page_wheel $page.viewport %D]
    pack $page.scrollbar -side right -fill y -padx {5 0}
    pack $page.viewport -side left -fill both -expand 1
    return $page.viewport.body
}

proc ::os::scroll_page_bind {parent viewport} {
    foreach child [winfo children $parent] {
        if {[winfo class $child] ne "Text"} {
            bind $child <MouseWheel> [list ::os::scroll_page_wheel $viewport %D]
        }
        ::os::scroll_page_bind $child $viewport
    }
}

proc ::os::build_inspector {panel} {
    ttk::frame $panel -padding {18 20} -style Panel.TFrame -width 342
    pack propagate $panel 0
    ttk::label $panel.heading -text "元素屬性" -style Heading.TLabel
    ttk::label $panel.detail -text "點選畫布上的文字或圖形，即可在這裡編輯。" -style Muted.TLabel -wraplength 300
    pack $panel.heading -anchor w -pady {0 8}
    pack $panel.detail -anchor w -pady {0 20}
    ttk::notebook $panel.tabs
    ttk::frame $panel.tabs.content -padding {0 14}
    ttk::frame $panel.tabs.geometry -padding {0 14}
    ttk::frame $panel.tabs.advanced -padding {8 18}
    $panel.tabs add $panel.tabs.content -text "內容"
    $panel.tabs add $panel.tabs.geometry -text "位置"
    $panel.tabs add $panel.tabs.advanced -text "進階"
    set page $panel.tabs.content
    set body [::os::scroll_page $page]
    ttk::label $page.label -text "文字內容"
    text $page.text -height 3 -wrap word -font {Arial 14} -undo 1 -background #151c22 -foreground #e9f1ee -insertbackground #92dfc1 -selectbackground #34584f -borderwidth 0 -highlightthickness 1 -highlightbackground #3c4850 -highlightcolor #8bddbb -padx 10 -pady 10
    pack $page.label -in $body -anchor w -pady {0 6}
    pack $page.text -in $body -fill x -pady {0 10}
    ttk::frame $page.font
    foreach {key label row} {font_family 西文字型 0 east_asian_font 中文（選填） 1 font_size 字級 2} {
        ttk::label $page.font.${key}_label -text $label
        ttk::entry $page.font.$key -textvariable ::os::form($key) -width 15
        grid $page.font.${key}_label -row $row -column 0 -sticky w -pady 6
        grid $page.font.$key -row $row -column 1 -sticky ew -padx {12 0} -pady 6
    }
    ttk::checkbutton $page.font.bold -text "粗體" -variable ::os::form(bold)
    ttk::combobox $page.font.align -values {靠左 置中 靠右} -textvariable ::os::form(alignment) -state readonly -width 13
    grid $page.font.bold -row 3 -column 0 -sticky w -pady 8
    grid $page.font.align -row 3 -column 1 -sticky ew -padx {12 0} -pady 8
    grid columnconfigure $page.font 1 -weight 1
    pack $page.font -in $body -fill x -pady {0 8}
    ttk::frame $page.colors
    ::os::color_field $page.colors color 文字 0
    ::os::color_field $page.colors fill 填色 1
    ::os::color_field $page.colors stroke 邊框 2
    pack $page.colors -in $body -fill x
    ::os::scroll_page_bind $page $page.viewport
    set page $panel.tabs.geometry
    set body [::os::scroll_page $page]
    ttk::label $page.units -text "畫布單位：像素" -style Muted.TLabel
    grid $page.units -in $body -row 0 -columnspan 2 -sticky w -pady {0 18}
    set row 1
    foreach {key label} {x 水平位置 y 垂直位置 width 寬度 height 高度 stroke_width 邊框粗細} {
        ttk::label $page.${key}_label -text $label
        ttk::entry $page.$key -textvariable ::os::form($key) -width 13
        grid $page.${key}_label -in $body -row $row -column 0 -sticky w -pady 12
        grid $page.$key -in $body -row $row -column 1 -sticky ew -padx {16 0} -pady 12
        incr row
    }
    grid columnconfigure $body 1 -weight 1
    ::os::scroll_page_bind $page $page.viewport
    set page $panel.tabs.advanced
    ttk::label $page.identifier -text "尚未選取元素" -wraplength 275 -style Muted.TLabel
    ttk::label $page.help -text "需要修改其他屬性時，可以開啟完整的元素資料。格式驗證通過後才會儲存。" -wraplength 275
    ttk::button $page.raw -text "編輯元素 JSON" -command ::os::advanced_element -state disabled
    pack $page.identifier $page.help -anchor w -pady {0 18}
    pack $page.raw -fill x
    ttk::frame $panel.actions
    ttk::button $panel.apply -text "套用變更" -style Primary.TButton -command ::os::apply_inspector -state disabled
    ttk::label $panel.notice -text "所有變更都可以復原" -style Muted.TLabel -wraplength 300
    pack $panel.actions -side bottom -fill x
    pack $panel.apply -in $panel.actions -fill x -pady {14 8}
    pack $panel.notice -in $panel.actions -anchor w
    pack $panel.tabs -side top -fill both -expand 1
}

proc ::os::shortcut {action args} {
    set active [focus]
    if {$active ne "" && $active ne "." && $active ne ".body.canvas"} {return}
    switch -- $action {
        full {::os::full}
        presenter {::os::presenter}
        default {::os::emit $action {*}$args}
    }
}

proc ::os::export_dialog {kind} {
    set extension [expr {$kind eq "pptx" ? ".pptx" : ".html"}]
    set target [tk_getSaveFile -defaultextension $extension -filetypes [list [list $kind *$extension]]]
    if {$target ne ""} {::os::emit export $kind $target}
}

proc ::os::open_dialog {} {
    set path [tk_getOpenFile -filetypes {{"Slide JSON" {.json}}}]
    if {$path ne ""} {::os::emit open $path}
}
proc ::os::new_dialog {} {
    set path [tk_getSaveFile -defaultextension .json -filetypes {{"Slide JSON" {.json}}}]
    if {$path ne ""} {::os::emit new $path}
}

proc ::os::presenter {} {
    if {[winfo exists .presenter]} {raise .presenter; return}
    toplevel .presenter
    wm title .presenter "講者模式"
    wm geometry .presenter 1180x800
    frame .presenter.previews -background #12252e
    canvas .presenter.previews.current -background #12252e -highlightthickness 0
    canvas .presenter.previews.next -background #12252e -highlightthickness 0
    pack .presenter.previews.current .presenter.previews.next -side left -fill both -expand 1
    pack .presenter.previews -side top -fill both -expand 1
    label .presenter.caption -font {Arial 16} -background #12252e -foreground #97e8c8 -pady 14
    pack .presenter.caption -fill x
    text .presenter.notes -height 7 -font {Arial 22} -wrap word -padx 24 -pady 20 -background #f1f6f8
    pack .presenter.notes -fill x
    frame .presenter.actions
    ttk::button .presenter.actions.previous -text "上一頁" -command {::os::emit previous}
    ttk::button .presenter.actions.next -text "下一頁" -command {::os::emit next}
    ttk::button .presenter.actions.save -text "儲存備註" -command {::os::emit notes [.presenter.notes get 1.0 end-1c]}
    ttk::button .presenter.actions.reset -text "重設計時" -command {set ::os::started [clock seconds]}
    label .presenter.actions.timer -font {Arial 18}
    pack .presenter.actions.previous .presenter.actions.next .presenter.actions.save .presenter.actions.reset .presenter.actions.timer -side left -padx 10 -pady 10
    pack .presenter.actions -fill x
    bind .presenter.previews <Configure> {after idle ::os::presenter_render}
    ::os::presenter_render
}

proc ::os::presenter_render {} {
    variable elements
    variable following
    variable background
    variable next_background
    variable next_title
    variable notes
    if {![winfo exists .presenter]} {return}
    .presenter.notes configure -font [list $::os::notes_family 22]
    ::os::paint .presenter.previews.current $elements $background
    ::os::paint .presenter.previews.next $following $next_background
    .presenter.caption configure -text "目前投影片                         下一頁：$next_title"
    if {[focus] ne ".presenter.notes"} {
        .presenter.notes delete 1.0 end
        .presenter.notes insert 1.0 $notes
    }
}

proc ::os::tick {} {
    variable started
    set elapsed [expr {[clock seconds]-$started}]
    if {[winfo exists .presenter.actions.timer]} {
        .presenter.actions.timer configure -text [format "%02d:%02d" [expr {$elapsed/60}] [expr {$elapsed%60}]]
    }
    after 1000 ::os::tick
}

proc ::os::smoke {} {after 300 ::os::smoke_now}
proc ::os::smoke_now {} {
    variable elements
    update idletasks
    ::os::finish
    set rendered [llength [.body.canvas find withtag element]]
    set expected [llength $elements]
    ::os::presenter
    update idletasks
    ::os::presenter_render
    set presenter [winfo exists .presenter.previews.next]
    if {[dict size $::os::raster_pending] > 0} {after 100 ::os::smoke_now; return}
    set patch [info patchlevel]
    ::os::emit smoke "{\"ok\":true,\"tcl_version\":\"$patch\",\"expected_elements\":$expected,\"rendered_items\":$rendered,\"presenter_window\":$presenter}"
}

if {[lsearch -exact [ttk::style theme names] clam] >= 0} {ttk::style theme use clam}
option add *Font {Arial 13}
option add *TCombobox*Listbox.background #202830
option add *TCombobox*Listbox.foreground #edf3f0
ttk::style configure . -background #202830 -foreground #edf3f0 -font {Arial 13}
ttk::style configure TFrame -background #202830
ttk::style configure Panel.TFrame -background #202830
ttk::style configure TLabel -background #202830 -foreground #edf3f0
ttk::style configure Heading.TLabel -font {Arial 18 bold}
ttk::style configure Brand.TLabel -font {Arial 16 bold} -foreground #9be4c7
ttk::style configure Muted.TLabel -foreground #a4b3ba -font {Arial 12}
ttk::style configure TButton -background #303b43 -foreground #edf3f0 -borderwidth 0 -padding {12 9}
ttk::style map TButton -background {active #40534f pressed #365c51 disabled #242d33} -foreground {disabled #66767d}
ttk::style configure Primary.TButton -background #92dfc1 -foreground #122922 -font {Arial 13 bold}
ttk::style map Primary.TButton -background {active #b3eed8 pressed #72cba8 disabled #344941} -foreground {disabled #809d90}
ttk::style configure TEntry -fieldbackground #151c22 -foreground #edf3f0 -insertcolor #92dfc1 -padding 7
ttk::style map TEntry -fieldbackground {disabled #202830} -foreground {disabled #72818a}
ttk::style configure TCombobox -fieldbackground #151c22 -background #303b43 -foreground #edf3f0 -padding 7
ttk::style map TCombobox -fieldbackground {readonly #151c22 disabled #202830} -foreground {disabled #72818a readonly #edf3f0}
ttk::style configure TCheckbutton -background #202830 -foreground #edf3f0
ttk::style map TCheckbutton -background {active #202830} -foreground {disabled #72818a}
ttk::style configure TNotebook -background #202830 -borderwidth 0
ttk::style configure TNotebook.Tab -background #202830 -foreground #9aaab2 -padding {14 10}
ttk::style map TNotebook.Tab -background {selected #303c43} -foreground {selected #9be4c7}
wm title . "Open Slide — Python + Tcl/Tk"
wm geometry . 1440x900
wm minsize . 1080 680
. configure -background #11171c
ttk::frame .toolbar -padding {18 14}
ttk::label .toolbar.brand -text "OPEN SLIDE" -style Brand.TLabel
pack .toolbar.brand -side left -padx {0 22}
foreach {name text action} {
    new 新增 ::os::new_dialog
    open 開啟 ::os::open_dialog
    undo 復原 {::os::emit undo}
    redo 重做 {::os::emit redo}
    source 進階資料 {::os::emit source}
} {
    ttk::button .toolbar.$name -text $text -command $action
    pack .toolbar.$name -side left -padx 3
}
foreach {name text action} {
    pptx 匯出PPTX {::os::export_dialog pptx}
    html 匯出HTML {::os::export_dialog html}
    presenter 講者模式 ::os::presenter
    fullscreen 播放 ::os::full
} {
    ttk::button .toolbar.$name -text $text -command $action
    if {$name eq "fullscreen"} {.toolbar.$name configure -style Primary.TButton}
    pack .toolbar.$name -side right -padx 3
}
pack .toolbar -side top -fill x
frame .footer -background #171e24 -padx 18 -pady 8
label .status -background #171e24 -foreground #acbdc4 -font {Arial 12} -anchor w
pack .status -in .footer -side left -fill x -expand 1
ttk::frame .paging -padding {10 5}
ttk::button .paging.previous -text "上一頁" -command {::os::emit previous}
ttk::button .paging.next -text "下一頁" -command {::os::emit next}
ttk::label .paging.position -textvariable ::os::page_label -width 9 -anchor center
set ::os::page_label "1 / 1"
pack .paging.previous .paging.position .paging.next -side left -padx 3
pack .paging -in .footer -side right
pack .footer -side bottom -fill x
frame .body -background #11171c
ttk::frame .body.sidebar -padding {14 18} -width 236
pack propagate .body.sidebar 0
ttk::label .body.sidebar.heading -text "投影片" -style Heading.TLabel
ttk::label .body.sidebar.count -text "1 張投影片" -style Muted.TLabel
pack .body.sidebar.heading -anchor w
pack .body.sidebar.count -anchor w -pady {8 16}
listbox .body.list -width 22 -background #202830 -foreground #d4dfdc -selectbackground #39594e -selectforeground #b5f0d9 -font {Arial 13} -borderwidth 0 -highlightthickness 0 -activestyle none -exportselection 0
pack .body.list -in .body.sidebar -fill both -expand 1
ttk::frame .body.sidebar.actions
ttk::button .body.sidebar.actions.duplicate -text "複製" -width 7 -command {::os::emit duplicate_slide}
ttk::button .body.sidebar.actions.delete -text "刪除" -width 7 -command {::os::emit delete_slide}
pack .body.sidebar.actions.duplicate .body.sidebar.actions.delete -side left -expand 1 -fill x -padx 3
pack .body.sidebar.actions -fill x -pady {14 8}
ttk::frame .body.sidebar.order
ttk::button .body.sidebar.order.up -text "上移" -width 7 -command {::os::emit move_slide -1}
ttk::button .body.sidebar.order.down -text "下移" -width 7 -command {::os::emit move_slide 1}
pack .body.sidebar.order.up .body.sidebar.order.down -side left -expand 1 -fill x -padx 3
pack .body.sidebar.order -fill x
::os::build_inspector .body.inspector
canvas .body.canvas -background #11171c -highlightthickness 0 -takefocus 1
pack .body.sidebar -side left -fill y
pack .body.inspector -side right -fill y
pack .body.canvas -side left -fill both -expand 1
pack .body -fill both -expand 1
bind .body.canvas <Configure> ::os::schedule_render
bind .body.list <<ListboxSelect>> ::os::pick
bind .body.canvas <Button-1> {focus .body.canvas; ::os::hit %x %y}
bind .body.canvas <Double-Button-1> {focus .body.canvas; ::os::hit %x %y}
bind . <Right> {::os::shortcut next}
bind . <Left> {::os::shortcut previous}
bind . <space> {::os::shortcut next}
bind . <Home> {::os::shortcut jump 0}
bind . <End> {::os::shortcut jump [expr {$::os::total-1}]}
bind . <Key-f> {::os::shortcut full}
bind . <Key-p> {::os::shortcut presenter}
bind . <Control-z> {::os::shortcut undo}
bind . <Control-y> {::os::shortcut redo}
if {[tk windowingsystem] eq "aqua"} {
    bind . <Command-z> {::os::shortcut undo}
    bind . <Command-Shift-z> {::os::shortcut redo}
}
bind . <Escape> ::os::escape
fconfigure stdin -blocking 0 -encoding utf-8
fconfigure stdout -encoding utf-8 -buffering line
fileevent stdin readable ::os::receive
::os::tick
::os::emit ready
