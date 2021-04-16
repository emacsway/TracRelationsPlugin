/*
 Copyright (C) 2021 Cinc

 This software is licensed as described in the file COPYING, which
 you should have received as part of this distribution.
*/
jQuery(document).ready(function($) {
  function apply_transform(filter_list){
      var i;
      for(i = 0; i < filter_list.length; i++){
        var html = filter_list[i];
        switch(html['pos']){
          case 'after':
            $(html['css']).after(html['html']);
            break;
          case 'append':
            $(html['css']).append(html['html']);
            break;
          case 'before':
            $(html['css']).before(html['html']);
            break;
          case 'prepend':
            $(html['css']).prepend(html['html']);
            break;
          case 'remove':
            $(html['css']).remove();
            break;
          case 'replace':
            $(html['css']).replaceWith(html['html']);
            break;
          default:
            break;
        };
      } // for
  };

  function manage_relations(event){
    $('#manage-rel-dialog').dialog('open');
    event.preventDefault();
  };

  function dialog_open(event, ui){
    console.log('Opening dialog')
    $('#m-r-body').load(tktrel_manageurl)
  };

  function resolution_change(event){
    if(this.value === 'duplicate'){
      $('#tktrel-duplicate-id').show();
      }
    else {
      $('#tktrel-id-input').val('')
      $('#tktrel-duplicate-id').hide();
    };
  };

  if(typeof tktrel_filter !== 'undefined'){
      apply_transform(tktrel_filter);
  };

  $("#action_resolve_resolve_resolution").on('change', resolution_change);


  var dialog_width = $(window).width() * 0.4;

  $('#manage-rel-form').submit(manage_relations);
  $('#manage-rel-dialog').dialog({
                                  open: dialog_open,
                                  width: dialog_width,
                                  modal: true,
                                  position: {my: 'top', at: "top+5%"},
                                  autoOpen: false,
                                     buttons: [{
                                                  text: "Ok",
                                                  click: function() {
                                                    $( this ).dialog( "close" );
                                                  }
                                              }]
                                    });

});
